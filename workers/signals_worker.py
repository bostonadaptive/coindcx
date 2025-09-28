"""
Signals worker - run as a separate process in production. Connects to market stream
and computes signals per tick for active strategies, writing to Redis for fast reads
by web processes.

Usage:
  REDIS_URL=redis://localhost:6379 python workers/signals_worker.py

Notes:
 - Requires `redis` and `python-socketio` for optional socket streaming.
 - This script is a scaffold; adapt subscription channels and parsing to the live
   exchange stream you use.
"""
import os, time, json
from datetime import datetime, timedelta
import traceback

try:
    import redis
except Exception:
    redis = None

try:
    import socketio
except Exception:
    socketio = None

# local imports via package
from app import STRATEGY_MAP, tv_to_pair_market, redis_set_signal, redis_get_signal, fetch_candles
from model import db, UserStrategySetup, Strategy

REDIS_URL = os.environ.get('REDIS_URL')
if not REDIS_URL:
    print('Please set REDIS_URL to use the signals worker. Exiting.'); raise SystemExit(1)


def _get_redis_client():
    """Return a redis client or None without raising on connect errors."""
    if not redis:
        return None
    try:
        return redis.from_url(REDIS_URL, decode_responses=True)
    except Exception:
        return None

# In-memory fallback cache when Redis is not reachable
INMEM_SIGNALS = {}


def _safe_redis_publish(key, record, ttl=60):
    """Try to write `record` to Redis and publish an update. If Redis is
    unavailable, store in an in-memory dict and log a warning.
    The redis-py `hmset` method is deprecated; use `hset` with mapping.
    """
    try:
        rr = _get_redis_client()
        if not rr:
            raise RuntimeError('redis client unavailable')
        # prefer hset with mapping for modern redis-py
        rr.hset(key, mapping=record)
        rr.expire(key, ttl)
        # publish minimal payload for subscribers
        rr.publish('signals:updates', json.dumps({'id': key.split(':',1)[-1], 'signal': record.get('signal')}))
    except Exception as e:
        # connection error or other Redis error - fallback to memory
        try:
            err_msg = str(e)
        except Exception:
            err_msg = repr(e)
        # print(f"signals_worker: Redis unavailable ({err_msg}), using in-memory fallback for {key}")
    INMEM_SIGNALS[key] = dict(record, updated_at=record.get('updated_at', int(time.time()*1000)))


def compute_and_store(us_id, symbol, strategy_name):
    try:
        # pair_market from symbol (expecting tv symbol like 'BINANCE:BTCUSDT' or 'BTCUSDT')
        pair_market = tv_to_pair_market(symbol)
        end_dt = datetime.utcnow()
        # Worker candle window in days (smaller default for speed). Can be overridden by env.
        days = int(os.environ.get('WORKER_CANDLE_DAYS', '3'))
        start_dt = end_dt - timedelta(days=days)
        candles = fetch_candles(pair_market, '15m', start_dt, end_dt)
        if not candles or len(candles) < 20:
            rec = {'signal':'-', 'updated_at': int(time.time()*1000), 'symbol': symbol}
            key = f'signals:{us_id}'
            _safe_redis_publish(key, rec)
            return
        import pandas as pd
        df = pd.DataFrame([{'time':c.get('t'),'open':c.get('o'),'high':c.get('h'),'low':c.get('l'),'close':c.get('c')} for c in candles])
        func = STRATEGY_MAP.get(strategy_name.lower(), {}).get('func')
        if not func:
            rec={'signal':'-','updated_at':int(time.time()*1000),'symbol':symbol}
        else:
            df_signals = func(df)
            if getattr(df_signals,'empty',True): rec={'signal':'-','updated_at':int(time.time()*1000),'symbol':symbol}
            else:
                last = df_signals.iloc[-1]
                sig = 'BUY' if last.get('buy_signal') else ('SELL' if last.get('sell_signal') else 'HOLD')
                rec = {'signal':sig,'updated_at':int(time.time()*1000),'symbol':symbol}
        key = f'signals:{us_id}'
        _safe_redis_publish(key, rec)
    except Exception:
        traceback.print_exc()

def build_symbol_map():
    """Return a dict: symbol_upper -> list of (us_id, strategy_name, symbol_tv)
    where symbol_upper is like 'BTCUSDT' (cleaned).
    """
    from model import UserStrategySetup, Strategy
    rows = db.session.query(UserStrategySetup, Strategy).join(Strategy).filter(UserStrategySetup.is_active == True).all()
    m = {}
    for us, strat in rows:
        # cleaned symbol
        try:
            cleaned = us.symbol.split(':')[-1].split('_')[-1].upper()
        except Exception:
            cleaned = (us.symbol or '').upper()
        m.setdefault(cleaned, []).append((us.id, strat.name, us.symbol))
    return m


def run_worker_loop():
    from model import UserStrategySetup, Strategy
    from model import db
    # Import the Flask app and run inside its application context so SQLAlchemy
    # can be used safely from this separate process.
    try:
        from app import app as flask_app
    except Exception:
        flask_app = None

    # print('signals_worker starting (live mode if socket available)...')

    # start an in-memory flusher thread that will attempt to push cached signals
    # to Redis when it becomes reachable
    def flush_inmem_once():
        """Attempt to flush INMEM_SIGNALS to Redis once. Returns number flushed."""
        if not INMEM_SIGNALS:
            return 0
        if not redis:
            print('flush_inmem_once: redis module not available')
            return 0
        try:
            rr = redis.from_url(REDIS_URL, decode_responses=True)
            rr.ping()
        except Exception as e:
            # Redis still unreachable
            # print minimal message for debug
            print('flush_inmem_once: redis unreachable ->', e)
            return 0

        flushed = 0
        keys = list(INMEM_SIGNALS.keys())
        for k in keys:
            rec = INMEM_SIGNALS.get(k)
            if not rec:
                INMEM_SIGNALS.pop(k, None)
                continue
            try:
                rr.hset(k, mapping=rec)
                rr.expire(k, 120)
                rr.publish('signals:updates', json.dumps({'id': k.split(':',1)[-1], 'signal': rec.get('signal')}))
                INMEM_SIGNALS.pop(k, None)
                flushed += 1
                # print(f'flush_inmem_once: flushed {k} -> {rec.get("signal")}')
            except Exception as e:
                print(f'flush_inmem_once: failed to write {k} -> {e}')
                # stop on first failure to avoid hammering redis
                break
        return flushed
    def _inmem_flusher_loop(interval: int = 5):
        while True:
            try:
                if INMEM_SIGNALS and redis:
                    try:
                        flush_inmem_once()
                    except Exception as e:
                        print('inmem flusher error:', e)
            except Exception:
                pass
            time.sleep(interval)

    try:
        import threading
        flusher_t = threading.Thread(target=_inmem_flusher_loop, daemon=True, name='inmem-flusher')
        flusher_t.start()
    except Exception:
        pass

    # run the worker loop inside Flask app context if available
    if flask_app:
        with flask_app.app_context():
            symbol_map = build_symbol_map()
            last_map_refresh = time.time()
            _run_loop_core(symbol_map, last_map_refresh)
    else:
        # fallback if app import failed
        symbol_map = build_symbol_map()
        last_map_refresh = time.time()
        _run_loop_core(symbol_map, last_map_refresh)


def _run_loop_core(symbol_map, last_map_refresh):
    """Core loop extracted to run inside or outside Flask app context."""
    # If socketio available, try connecting to public stream and subscribe to batched price updates
    if socketio:
        try:
            sio = socketio.Client(logger=False, reconnection=True, reconnection_attempts=999)

            @sio.event
            def connect():
                # print('worker: connected to stream')
                # join broad channel for batched updates if supported
                try:
                    sio.emit('join', {'channelName': 'currentPrices@spot@10s'})
                except Exception:
                    pass

            @sio.on('price-change')
            def on_price_change(msg):
                try:
                    # msg may be a dict or a JSON string depending on server
                    data = (msg and (msg.get('data') or msg)) or {}
                    if isinstance(data, str):
                        try:
                            data = json.loads(data)
                        except Exception:
                            data = {}
                    # obtain label like 'B-BTC_USDT' or 'BTCUSDT'
                    label = data.get('s') or data.get('symbol') or data.get('channel')
                    price = data.get('p') or data.get('price') or data.get('c') or data.get('last_price')
                    if not label:
                        return
                    s = str(label).upper()
                    if s.startswith('B-'):
                        s = s[2:].replace('_','')
                    s = s.replace(':','').replace('/','')
                    # compute for matching user configs
                    targets = symbol_map.get(s)
                    if targets:
                        for us_id, strat_name, tv_sym in targets:
                            compute_and_store(us_id, tv_sym, strat_name)
                except Exception:
                    traceback.print_exc()

            @sio.on('currentPrices@spot#update')
            def on_batch_update(msg):
                try:
                    data = (msg and (msg.get('data') or msg)) or {}
                    if isinstance(data, str):
                        try:
                            data = json.loads(data)
                        except Exception:
                            data = {}
                    prices = data.get('prices') or data.get('pr') or {}
                    if not prices:
                        return
                    for k,v in prices.items():
                        label = str(k).upper()
                        if label.startswith('B-'):
                            label = label[2:].replace('_','')
                        cleaned = label.replace(':','').replace('/','')
                        targets = symbol_map.get(cleaned)
                        if not targets:
                            continue
                        for us_id, strat_name, tv_sym in targets:
                            compute_and_store(us_id, tv_sym, strat_name)
                except Exception:
                    traceback.print_exc()

            try:
                STREAM_BASE = os.environ.get('COINDCX_STREAM') or os.environ.get('COINDCX_STREAM_URL') or 'https://stream.coindcx.com'
                sio.connect(STREAM_BASE, transports=['websocket'])
            except Exception:
                print('worker: socket connect failed, falling back to polling')
                sio = None

            # main loop: refresh symbol_map periodically; keep socket handlers running
            while True:
                try:
                    now = time.time()
                    if now - last_map_refresh > 5:
                        symbol_map = build_symbol_map()
                        last_map_refresh = time.time()
                    time.sleep(1)
                except KeyboardInterrupt:
                    break
                except Exception:
                    traceback.print_exc(); time.sleep(1)

        except Exception:
            traceback.print_exc()

    # Fallback: periodic polling loop (if socketio not available or connection failed)
    try:
        while True:
            try:
                symbol_map = build_symbol_map()
                # compute for all entries in batches
                for sym, targets in symbol_map.items():
                    # choose a default tf and fetch candles
                    for us_id, strat_name, tv_sym in targets:
                        compute_and_store(us_id, tv_sym, strat_name)
                time.sleep(5)
            except KeyboardInterrupt:
                break
            except Exception:
                traceback.print_exc(); time.sleep(3)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    run_worker_loop()

"""
Test-only signals worker.

This script is intended to be used only in development/testing. It looks up active
strategies in the DB where `is_paper = True and is_active = True`, fetches recent
candles, computes short and long EMA and treats short>long as BUY and short<long as SELL.
When a signal is detected it will:
 - log the detection
 - create a PaperTrade row (simulating opening an order)
 - log DB insertion

This script is intended to be easy to enable/disable and separate from the production
`signals_worker.py`. You can run it with:

    python workers/test_signals_worker.py

Or run once and exit:

    RUN_ONCE=1 python workers/test_signals_worker.py

NOTE: This script runs within the Flask app context so it can use `db` safely.
It is purposely verbose.
"""
import os, time, traceback, json
from datetime import datetime, timedelta

from app import app
from model import db, UserStrategySetup, PaperTrade

# config
SHORT_EMA = int(os.environ.get('TEST_SHORT_EMA', '8'))
LONG_EMA = int(os.environ.get('TEST_LONG_EMA', '21'))
TF = os.environ.get('TEST_TF', '15m')
RUN_ONCE = bool(os.environ.get('RUN_ONCE', '0'))

# helper: simple EMA using pandas if available, otherwise basic calc
try:
    import pandas as pd
except Exception:
    pd = None


def compute_emas(closes, span_short=SHORT_EMA, span_long=LONG_EMA):
    if pd is None:
        # fallback: simple SMA-like rolling average (not ideal) for dev
        short = sum(closes[-span_short:]) / span_short if len(closes) >= span_short else None
        long = sum(closes[-span_long:]) / span_long if len(closes) >= span_long else None
        return short, long
    s = pd.Series(closes)
    ema_short = s.ewm(span=span_short, adjust=False).mean().iloc[-1]
    ema_long = s.ewm(span=span_long, adjust=False).mean().iloc[-1]
    return float(ema_short), float(ema_long)


def fetch_recent_closes(tv_symbol, tf=TF, lookback_hours=48):
    # Reuse app.fetch_candles if available
    try:
        pair = app.tv_to_pair_market(tv_symbol) if hasattr(app, 'tv_to_pair_market') else None
    except Exception:
        pair = None
    # best-effort: call public function if present
    try:
        from app import fetch_candles
        end = datetime.utcnow()
        start = end - timedelta(hours=lookback_hours)
        c = fetch_candles(pair or tv_symbol, tf, start, end)
        closes = [float(x.get('c') or 0) for x in c]
        return closes
    except Exception:
        traceback.print_exc()
        return []


def run_once():
    print('test_signals_worker: running once - scanning for paper active strategies')
    rows = UserStrategySetup.query.filter_by(is_active=True, is_paper=True).all()
    print(f'Found {len(rows)} strategies to test')
    for us in rows:
        try:
            print('---')
            print('Strategy id:', us.id, 'symbol:', us.symbol, 'leverage:', us.leverage, 'margin:', us.margin)
            closes = fetch_recent_closes(us.symbol)
            if not closes or len(closes) < 10:
                print('Not enough candles for', us.symbol); continue
            short, long = compute_emas(closes)
            print('EMA short:', short, 'EMA long:', long)
            if short is None or long is None:
                print('Could not compute EMAs for', us.id); continue
            signal = None
            if short > long:
                signal = 'BUY'
            elif short < long:
                signal = 'SELL'
            else:
                signal = 'HOLD'
            print('Signal detected for', us.id, ':', signal)

            # If BUY or SELL, create a PaperTrade to simulate opening an order
            if signal in ('BUY', 'SELL'):
                # Simulate order price as last close
                price = closes[-1]
                qty = 0.0
                try:
                    notional = float(us.margin or 0) * max(int(us.leverage or 1), 1)
                    qty = notional / price if price>0 else 0
                except Exception:
                    qty = 0.0
                import uuid
                poid = f"PAPER-{uuid.uuid4().hex}"
                pt = PaperTrade(
                    user_id=us.user_id,
                    config_id=us.id,
                    symbol=us.symbol,
                    tv_symbol=None,
                    side='BUY' if signal=='BUY' else 'SELL',
                    qty=qty,
                    entry_price=price,
                    entry_time=datetime.utcnow(),
                    margin=us.margin or 0,
                    leverage=us.leverage or 1,
                    locked_amount=(us.margin or 0),
                    pnl_inr=0.0,
                    status='OPEN',
                    strategy='',  # optional
                    paper_order_id=poid
                )
                db.session.add(pt)
                db.session.commit()
                print('PaperTrade inserted id=', pt.id, 'side=', pt.side, 'qty=', pt.qty, 'entry_price=', pt.entry_price)
            else:
                print('No actionable signal for', us.id)
        except Exception:
            traceback.print_exc()


def main():
    with app.app_context():
        if RUN_ONCE:
            run_once(); return
        print('test_signals_worker: starting continuous loop (Ctrl-C to stop)')
        while True:
            try:
                run_once()
            except KeyboardInterrupt:
                break
            except Exception:
                traceback.print_exc()
            time.sleep(5)


if __name__ == '__main__':
    main()

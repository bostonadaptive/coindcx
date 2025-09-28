import json, sqlite3
import time
import hmac
import hashlib
import math
import pandas as pd
import ta
import numpy as np
import collections
from collections import defaultdict
import requests
try:
    # optional dependency for loading .env files in development
    from dotenv import load_dotenv
except Exception:
    def load_dotenv(*a, **k):
        # no-op if python-dotenv isn't installed; environment variables
        # may still be provided by the system or container.
        return
import os
from decimal import Decimal
from functools import wraps
from typing import Any, Dict, List, Tuple, Optional
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
import threading
# from technical_strategies import STRATEGY_MAP

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, g
)

from model import (
    db, User, Credentials, Watchlist, Strategy, PaperWallet, UserStrategySetup,
    TradeHistory, Role, ModeratorEarnings, UserStrategyConfig, BacktestConfig, BacktestRun,
    PaperTrade, StrategySignal
)

# from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from forms import StrategyForm, StrategyPopupForm

# ------------------ Flask / DB ------------------
app = Flask(__name__)
app.secret_key = "supersecretkey"  # change for production
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///coindcx.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
# db = SQLAlchemy(app)

db.init_app(app)

# Jinja filter: show Coindcx pair name for a stored tv symbol like 'BINANCE:ETHUSDT' -> 'B-ETH_USDT'
@app.template_filter('coindcx_pair')
def jinja_coindcx_pair(tv_symbol: str) -> str:
    try:
        if not tv_symbol:
            return ''
        return tv_to_pair_market(tv_symbol)
    except Exception:
        return tv_symbol or ''

# Start LTP aggregator once app is ready to serve requests
def _start_aggregator():
    try:
        # allow disabling the aggregator in development to avoid socket connection spam
        if os.environ.get('DISABLE_LTP_AGG', '0') != '1':
            start_ltp_aggregator()
    except Exception:
        pass


# Start signals poller at startup
def _start_signals_poller():
    try:
        start_signals_poller()
    except Exception:
        pass

# Register the startup hook defensively. Some Flask builds may not expose the
# decorator attribute in certain environments; prefer calling the registration
# method if available, otherwise the function will be invoked from main below.
try:
    # app.before_first_request can be used as a decorator or called with a
    # function to register it. Use the callable form to avoid decorator lookup
    # failures on older or unusual Flask builds.
    app.before_first_request(_start_aggregator)
    app.before_first_request(_start_signals_poller)
except Exception:
    # Will fallback to calling _start_aggregator() in the __main__ block.
    pass

# Base URLs: prefer an MCP/proxy override if provided (useful for testing or alternate proxies)
# COINDCX_MCP (single URL) takes precedence and will be used for both API and public endpoints.
# Alternatively set COINDCX_API_BASE and/or COINDCX_PUBLIC_BASE separately.
_mcp_base = os.environ.get('COINDCX_MCP') or os.environ.get('COINDCX_PROXY')
API_BASE = os.environ.get('COINDCX_API_BASE') or _mcp_base or "https://api.coindcx.com"
PUBLIC_BASE = os.environ.get('COINDCX_PUBLIC_BASE') or _mcp_base or "https://public.coindcx.com"
# Streaming socket endpoint can be overridden with COINDCX_STREAM if needed (default remains coindcx stream)
STREAM_BASE = os.environ.get('COINDCX_STREAM') or os.environ.get('COINDCX_STREAM_URL') or 'https://stream.coindcx.com'

# Load environment variables from .env if present
load_dotenv()

# If python-dotenv wasn't available, provide a tiny .env loader fallback so
# developers who only set a local .env file still get their keys into os.environ.
def _tiny_load_dotenv(path='.env'):
    try:
        if not os.path.exists(path):
            return
        with open(path, 'r', encoding='utf-8') as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln or ln.startswith('#'):
                    continue
                if '=' not in ln:
                    continue
                k, v = ln.split('=', 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and (os.environ.get(k) is None):
                    os.environ[k] = v
    except Exception:
        pass

_tiny_load_dotenv('.env')

# Optional API credentials for server-side signed requests (from .env)
COINDCX_API_KEY = os.environ.get('COINDCX_API_KEY') or os.environ.get('API_KEY')
# Accept both COINDCX_API_SECRET and COINDCX_API_SECRET (typo-tolerant) and SECRET_KEY
COINDCX_SECRET = (os.environ.get('COINDCX_API_SECRET') or os.environ.get('COINDCX_API_SECRET')
                 or os.environ.get('COINDCX_SECRET') or os.environ.get('SECRET_KEY'))

# In-memory cache for latest LTPs populated by a background socket client
LTP_CACHE: dict[str, float] = {}
# Per-symbol last update timestamp (ms since epoch)
LTP_TS: dict[str, int] = {}
# Poll rotation index for server-side batching
LTP_POLL_INDEX: int = 0
# Default batch size (how many symbols to poll per interval). Can be tuned via env.
LTP_POLL_BATCH = int(os.environ.get('LTP_POLL_BATCH', '5'))

# SIGNAL CACHE: store precomputed signals for active user strategies.
# Keyed by user_strategy.id -> { 'signal': 'BUY'|'SELL'|'HOLD'|'-', 'updated_at': ts_ms, 'symbol': 'BTCUSDT' }
SIGNAL_CACHE: dict[int, dict] = {}
# TTL for cached signals (seconds)
SIGNAL_TTL = int(os.environ.get('SIGNAL_TTL_SEC', '10'))
# How many active strategies to compute per poll batch to spread load
SIGNAL_POLL_BATCH = int(os.environ.get('SIGNAL_POLL_BATCH', '50'))
# Poll interval seconds
SIGNAL_POLL_INTERVAL = float(os.environ.get('SIGNAL_POLL_INTERVAL', '2.0'))

# Optional Redis client for cross-process cache (recommended for production)
REDIS_URL = os.environ.get('REDIS_URL') or os.environ.get('REDIS_URI')
_redis = None
if REDIS_URL:
    try:
        import redis
        _redis = redis.from_url(REDIS_URL, decode_responses=True)
    except Exception:
        _redis = None

def redis_set_signal(us_id: int, rec: dict):
    """Store a signal record in Redis (hash)."""
    if not _redis:
        return False
    try:
        key = f"signals:{us_id}"
        try:
            _redis.hset(key, mapping={
                'signal': rec.get('signal','-'),
                'last_signal': rec.get('last_signal','-'),
                'updated_at': str(rec.get('updated_at',0)),
                'symbol': rec.get('symbol','')
            })
        except Exception:
            # Some redis versions or network errors may fail; ignore and continue
            pass
        # set TTL slightly larger than SIGNAL_TTL
        _redis.expire(key, max(30, SIGNAL_TTL*2))
        # also publish a lightweight update for realtime clients
        try:
            # publish full record for subscribers
            _redis.publish('signals:updates', json.dumps({'id': us_id, 'signal': rec.get('signal','-'), 'last_signal': rec.get('last_signal','-'), 'symbol': rec.get('symbol','')}))
        except Exception:
            pass
        return True
    except Exception:
        return False

def redis_get_signal(us_id: int):
    """Get signal record from Redis or return None."""
    if not _redis:
        return None
    try:
        key = f"signals:{us_id}"
        h = _redis.hgetall(key)
        if not h:
            return None
        return {
            'signal': h.get('signal','-'),
            'last_signal': h.get('last_signal','-'),
            'updated_at': int(h.get('updated_at') or 0),
            'symbol': h.get('symbol','')
        }
    except Exception:
        return None

def _compute_signal_for_user_strategy(us: 'UserStrategySetup', strategy_obj: 'Strategy') -> str:
    """Compute BUY/SELL/HOLD for a single UserStrategySetup using existing STRATEGY_MAP funcs.
    This is designed to be called in background or as fallback during request.
    Returns: 'BUY'|'SELL'|'HOLD'|'-'
    """
    try:
        # Build pair_market and timeframe
        pair_market = tv_to_pair_market(us.symbol)
        tf = (us.timeframe or '').lower()
        if tf == 'auto' or not tf:
            tf = STRATEGY_MAP.get((strategy_obj.name or '').lower(), {}).get('default_timeframes', ['15m'])[0]

        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(days=7)
        candles = fetch_candles(pair_market, tf, start_dt, end_dt)
        if not candles or len(candles) < 20:
            return '-'

        df = pd.DataFrame([{
            'time': c.get('t'), 'open': c.get('o'), 'high': c.get('h'), 'low': c.get('l'), 'close': c.get('c')
        } for c in candles])

        strat = STRATEGY_MAP.get((strategy_obj.name or '').lower(), {}).get('func')
        if not strat:
            return '-'

        df_signals = strat(df)
        if isinstance(df_signals, pd.DataFrame) and not df_signals.empty:
            last = df_signals.iloc[-1]
            if last.get('buy_signal'):
                return 'BUY'
            if last.get('sell_signal'):
                return 'SELL'
            return 'HOLD'
    except Exception:
        return '-'
    return '-'


def start_signals_poller():
    """Background thread that periodically computes signals for active strategies in batches and updates SIGNAL_CACHE.
    Designed to be light-weight and to spread load across ticks using SIGNAL_POLL_BATCH.
    """
    try:
        import threading

        def worker():
            global SIGNAL_CACHE
            # ensure DB tables for paper trading exist (safe no-op if already present)
            try:
                with app.app_context():
                    db.create_all()
                    # ensure we have a minimum amount of strategy_signals per active setup
                    try:
                        ensure_minimum_strategy_signals(min_per_setup=5)
                    except Exception:
                        # don't fail poller startup if backfill has issues
                        pass
            except Exception:
                pass
            while True:
                try:
                    # Fetch active strategies list (id, symbol, strategy)
                    rows = db.session.query(UserStrategySetup, Strategy).join(Strategy).filter(UserStrategySetup.is_active == True).all()
                    if not rows:
                        time.sleep(max(1.0, SIGNAL_POLL_INTERVAL))
                        continue

                    # Group by pair_market so we fetch candles only once per symbol
                    from collections import defaultdict
                    groups = defaultdict(list)  # pair_market -> list[(us, strat)]
                    for us, strat in rows:
                        try:
                            pair_market = tv_to_pair_market(us.symbol)
                        except Exception:
                            pair_market = tv_to_pair_market(us.symbol if us.symbol else '')
                        groups[pair_market].append((us, strat))

                    # Iterate groups in batches (pair-based batching)
                    pair_keys = list(groups.keys())
                    total_pairs = len(pair_keys)
                    p = 0
                    while p < total_pairs:
                        pair_batch = pair_keys[p:p+max(1, SIGNAL_POLL_BATCH)]
                        for pair_market in pair_batch:
                            try:
                                # fetch candles once for this pair
                                end_dt = datetime.now(timezone.utc)
                                start_dt = end_dt - timedelta(days=7)
                                # default tf: use 15m if unknown
                                # pick the first user timeframe in the group if available
                                first_us = groups[pair_market][0][0]
                                tf = (first_us.timeframe or '').lower()
                                if tf == 'auto' or not tf:
                                    tf = '15m'
                                candles = fetch_candles(pair_market, tf, start_dt, end_dt)
                                if not candles or len(candles) < 20:
                                    # mark as waiting for all users for this symbol (Latest waiting)
                                    for us, strat in groups[pair_market]:
                                        prev = SIGNAL_CACHE.get(us.id, {})
                                        last = prev.get('last_signal', '-')
                                        SIGNAL_CACHE[us.id] = {'signal': 'Waiting...', 'last_signal': last, 'updated_at': int(time.time()*1000), 'symbol': us.symbol}
                                        if _redis:
                                            redis_set_signal(us.id, SIGNAL_CACHE[us.id])
                                    continue

                                df = pd.DataFrame([{
                                    'time': c.get('t'), 'open': c.get('o'), 'high': c.get('h'), 'low': c.get('l'), 'close': c.get('c')
                                } for c in candles])

                                # compute signals for each strategy using the same df
                                for us, strat in groups[pair_market]:
                                    try:
                                        func = STRATEGY_MAP.get((str(strat.name or '')).lower(), {}).get('func')
                                        if not func:
                                            sig = '-'
                                        else:
                                            df_signals = func(df)
                                            if isinstance(df_signals, pd.DataFrame) and not df_signals.empty:
                                                last = df_signals.iloc[-1]
                                                if last.get('buy_signal'):
                                                    sig = 'BUY'
                                                elif last.get('sell_signal'):
                                                    sig = 'SELL'
                                                else:
                                                    sig = 'HOLD'
                                            else:
                                                sig = '-'

                                        prev = SIGNAL_CACHE.get(us.id, {})
                                        # last_signal should remember last non-HOLD, non-Waiting value
                                        last_signal = prev.get('last_signal', '-')
                                        if sig in ('BUY', 'SELL'):
                                            last_signal = sig

                                        rec = {'signal': sig if sig != '-' else 'Waiting...', 'last_signal': last_signal, 'updated_at': int(time.time()*1000), 'symbol': us.symbol}
                                        SIGNAL_CACHE[us.id] = rec
                                        if _redis:
                                            redis_set_signal(us.id, rec)
                                        # If this user-strategy is running in paper mode, process simulated trade
                                        try:
                                            if getattr(us, 'is_paper', False) and getattr(us, 'is_active', False):
                                                # current price from candles df
                                                cur_px = None
                                                try:
                                                    cur_px = float(df.iloc[-1]['close'])
                                                except Exception:
                                                    cur_px = None

                                                # compute moving-average trend confirmation (MA short=5, long=20)
                                                trend_confirmed = False
                                                try:
                                                    if isinstance(df, pd.DataFrame) and len(df) >= 20:
                                                        closes = df['close'].astype(float)
                                                        ma_short = closes.rolling(window=5).mean().iloc[-1]
                                                        ma_long = closes.rolling(window=20).mean().iloc[-1]
                                                        if sig == 'BUY' and ma_short > ma_long:
                                                            trend_confirmed = True
                                                        if sig == 'SELL' and ma_short < ma_long:
                                                            trend_confirmed = True
                                                except Exception:
                                                    trend_confirmed = False

                                                # run in app context to safely use DB session
                                                try:
                                                    with app.app_context():
                                                        process_paper_signal(us, sig, cur_px, strat.name if strat else None, trend_confirmed)
                                                except Exception:
                                                    pass
                                        except Exception:
                                            pass
                                    except Exception:
                                        prev = SIGNAL_CACHE.get(us.id, {})
                                        last = prev.get('last_signal', '-')
                                        rec = {'signal': 'Waiting...', 'last_signal': last, 'updated_at': int(time.time()*1000), 'symbol': us.symbol}
                                        SIGNAL_CACHE[us.id] = rec
                                        if _redis:
                                            redis_set_signal(us.id, rec)
                            except Exception:
                                # per-pair failure: mark group's signals as unavailable
                                for us, strat in groups[pair_market]:
                                    SIGNAL_CACHE[us.id] = {'signal': '-', 'updated_at': int(time.time()*1000), 'symbol': us.symbol}
                        p += max(1, SIGNAL_POLL_BATCH)
                        # small pause between pair batches
                        time.sleep(max(0.05, SIGNAL_POLL_INTERVAL/4.0))
                except Exception:
                    # keep the poller alive
                    time.sleep(2.0)

        t = threading.Thread(target=worker, daemon=True, name='signals-poller')
        t.start()
    except Exception:
        pass


def process_paper_signal(us: 'UserStrategySetup', sig: str, cur_price: Optional[float], strategy_name: Optional[str], trend_confirmed: bool = False):
    """Process a BUY/SELL signal for a user strategy in paper mode.
    - Open a new PaperTrade on BUY if no open trade exists for the config
    - Close existing open trade on opposite signal and record pnl
    This function runs inside app.app_context when called from the poller.
    """
    # Be explicit and deterministic: only react to BUY/SELL
    if sig not in ('BUY', 'SELL'):
        return

    # defensive: ensure we have a wallet for the user
    try:
        wallet = PaperWallet.query.filter_by(user_id=us.user_id).first()
        if not wallet:
            wallet = PaperWallet(user_id=us.user_id, balance=100000, available_balance=100000)
            db.session.add(wallet)
            db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return

    # debug log -- lightweight
    try:
        print(f"[process_paper_signal] config={getattr(us,'id',None)} user={getattr(us,'user_id',None)} sig={sig} cur_price={cur_price} strat={strategy_name} is_paper={getattr(us,'is_paper',None)} is_active={getattr(us,'is_active',None)}")
        print(f"  wallet: available={getattr(wallet,'available_balance',None)} balance={getattr(wallet,'balance',None)}")
        if open_trade:
            print(f"  existing open trade: id={getattr(open_trade,'id',None)} side={getattr(open_trade,'side',None)} entry_price={getattr(open_trade,'entry_price',None)} qty={getattr(open_trade,'qty',None)}")
        else:
            print("  no existing open trade for this setup")
    except Exception:
        pass

    # identify existing open trade for this user + strategy setup (any side)
    try:
        open_trade = PaperTrade.query.filter_by(user_id=us.user_id, config_id=us.id, status='OPEN').first()
    except Exception:
        open_trade = None

    # prefer per-setup margin/leverage if present
    margin = float(us.margin or 1000.0)
    leverage = int(us.leverage or 1)

    if open_trade:
        try:
            leverage = int(open_trade.leverage or leverage)
            margin = float(open_trade.margin or margin)
        except Exception:
            pass

    # approximate qty
    if cur_price and cur_price > 0:
        qty = (margin * max(1, leverage)) / float(cur_price)
    else:
        qty = 1.0

    # helper to recompute unrealized pnl
    def recompute_unrealized(user_id):
        try:
            opens = PaperTrade.query.filter_by(user_id=user_id, status='OPEN').all()
            total_unreal = 0.0
            for ot in opens:
                try:
                    if ot.entry_price and cur_price:
                        if ot.side == 'BUY':
                            ot.pnl_inr = (float(cur_price) - float(ot.entry_price)) * float(ot.qty)
                        else:
                            ot.pnl_inr = (float(ot.entry_price) - float(cur_price)) * float(ot.qty)
                        total_unreal += float(ot.pnl_inr or 0.0)
                except Exception:
                    continue
            w = PaperWallet.query.filter_by(user_id=user_id).first()
            if w:
                w.unrealized_pnl = total_unreal
                db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass

    # Main logic: handle BUY and SELL symmetrically per user's spec
    try:
        # BUY signal
        if sig == 'BUY':
            # If opposite open (SELL), close it
            if open_trade and open_trade.side == 'SELL':
                exit_px = cur_price or open_trade.entry_price
                try:
                    pnl = (float(open_trade.entry_price) - float(exit_px)) * float(open_trade.qty)
                except Exception:
                    pnl = 0.0
                open_trade.exit_price = exit_px
                open_trade.exit_time = datetime.utcnow()
                open_trade.status = 'CLOSED'
                # record a human-readable exit reason
                try:
                    open_trade.exit_reason = f"Closed on BUY signal (trend_confirmed={bool(trend_confirmed)})"
                except Exception:
                    pass
                open_trade.pnl_inr = pnl
                try:
                    wallet.realized_pnl = float(wallet.realized_pnl or 0.0) + float(pnl)
                    wallet.available_balance = float(wallet.available_balance or 0.0) + float(open_trade.locked_amount or 0.0) + float(pnl)
                    db.session.commit()
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                # update StrategySignal if present
                try:
                    if us and getattr(us, 'strategy_id', None) is not None:
                        ss = StrategySignal.query.filter_by(strategy_id=us.strategy_id, symbol=us.symbol, status='ACTIVE').order_by(StrategySignal.entry_time.desc()).first()
                        if ss:
                            ss.exit_price = exit_px
                            ss.exit_time = datetime.utcnow()
                            ss.status = 'EXITED'
                            try:
                                if ss.entry_price and float(ss.entry_price) > 0:
                                    if ss.direction and ss.direction.upper() in ('LONG','BUY'):
                                        ss.gain_ratio = (float(exit_px) - float(ss.entry_price)) / float(ss.entry_price)
                                    else:
                                        ss.gain_ratio = (float(ss.entry_price) - float(exit_px)) / float(ss.entry_price)
                            except Exception:
                                pass
                            db.session.commit()
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                recompute_unrealized(us.user_id)
            else:
                # no open trade -> open BUY
                if not open_trade:
                    if float(wallet.available_balance or 0.0) >= float(margin):
                        # generate a simulated order id for paper trades
                        import uuid
                        poid = f"PAPER-{uuid.uuid4().hex}"
                        pt = PaperTrade(user_id=us.user_id, config_id=us.id, symbol=us.symbol, side='BUY', qty=qty,
                                        entry_price=cur_price or None, entry_time=datetime.utcnow(), status='OPEN', strategy=str(strategy_name or ''),
                                        margin=margin, leverage=leverage, locked_amount=margin)
                        pt.paper_order_id = poid
                        db.session.add(pt)
                        try:
                            wallet.available_balance = float(wallet.available_balance or 0.0) - float(margin)
                            # record StrategySignal for open
                            try:
                                if us and getattr(us, 'strategy_id', None) is not None:
                                    ss = StrategySignal(strategy_id=us.strategy_id, symbol=us.symbol,
                                                        direction=('LONG' if pt.side == 'BUY' else 'SHORT'),
                                                        status='ACTIVE', entry_price=pt.entry_price, entry_time=pt.entry_time)
                                    db.session.add(ss)
                            except Exception:
                                pass
                            db.session.commit()
                        except Exception:
                            try:
                                db.session.rollback()
                            except Exception:
                                pass
                else:
                    # same-side open exists -> ignore (do nothing)
                    pass

        # SELL signal
        elif sig == 'SELL':
            # If opposite open (BUY), close it
            if open_trade and open_trade.side == 'BUY':
                exit_px = cur_price or open_trade.entry_price
                try:
                    pnl = (float(exit_px) - float(open_trade.entry_price)) * float(open_trade.qty)
                except Exception:
                    pnl = 0.0
                open_trade.exit_price = exit_px
                open_trade.exit_time = datetime.utcnow()
                open_trade.status = 'CLOSED'
                try:
                    open_trade.exit_reason = f"Closed on SELL signal (trend_confirmed={bool(trend_confirmed)})"
                except Exception:
                    pass
                open_trade.pnl_inr = pnl
                try:
                    wallet.realized_pnl = float(wallet.realized_pnl or 0.0) + float(pnl)
                    wallet.available_balance = float(wallet.available_balance or 0.0) + float(open_trade.locked_amount or 0.0) + float(pnl)
                    db.session.commit()
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                # update StrategySignal
                try:
                    if us and getattr(us, 'strategy_id', None) is not None:
                        ss = StrategySignal.query.filter_by(strategy_id=us.strategy_id, symbol=us.symbol, status='ACTIVE').order_by(StrategySignal.entry_time.desc()).first()
                        if ss:
                            ss.exit_price = exit_px
                            ss.exit_time = datetime.utcnow()
                            ss.status = 'EXITED'
                            try:
                                if ss.entry_price and float(ss.entry_price) > 0:
                                    if ss.direction and ss.direction.upper() in ('LONG','BUY'):
                                        ss.gain_ratio = (float(exit_px) - float(ss.entry_price)) / float(ss.entry_price)
                                    else:
                                        ss.gain_ratio = (float(ss.entry_price) - float(exit_px)) / float(ss.entry_price)
                            except Exception:
                                pass
                            db.session.commit()
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                recompute_unrealized(us.user_id)
            else:
                # no open trade -> open SELL
                opensell = PaperTrade.query.filter_by(user_id=us.user_id, config_id=us.id, status='OPEN', side='SELL').first()
                if not opensell:
                    if float(wallet.available_balance or 0.0) >= float(margin):
                        # generate a simulated order id for paper trades
                        import uuid
                        poid = f"PAPER-{uuid.uuid4().hex}"
                        pt = PaperTrade(user_id=us.user_id, config_id=us.id, symbol=us.symbol, side='SELL', qty=qty,
                                        entry_price=cur_price or None, entry_time=datetime.utcnow(), status='OPEN', strategy=str(strategy_name or ''),
                                        margin=margin, leverage=leverage, locked_amount=margin)
                        pt.paper_order_id = poid
                        db.session.add(pt)
                        try:
                            wallet.available_balance = float(wallet.available_balance or 0.0) - float(margin)
                            # record StrategySignal for open
                            try:
                                if us and getattr(us, 'strategy_id', None) is not None:
                                    ss = StrategySignal(strategy_id=us.strategy_id, symbol=us.symbol,
                                                        direction=('LONG' if pt.side == 'BUY' else 'SHORT'),
                                                        status='ACTIVE', entry_price=pt.entry_price, entry_time=pt.entry_time)
                                    db.session.add(ss)
                            except Exception:
                                pass
                            db.session.commit()
                        except Exception:
                            try:
                                db.session.rollback()
                            except Exception:
                                pass
                else:
                    # same-side SELL open exists -> ignore
                    pass

    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return

def start_ltp_aggregator():
    """Start a background socket.io client to subscribe to CoinDCX public
    currentPrices channel and update LTP_CACHE. This is best-effort and
    non-blocking. """
    try:
        import socketio
        import threading

        sio = socketio.Client(logger=False, reconnection=True)

        def _safe_join():
            try:
                sio.emit('join', {'channelName': 'currentPrices@spot@10s'})
            except Exception:
                pass

        @sio.event
        def connect():
            print('LTP aggregator connected')
            _safe_join()

        @sio.on('currentPrices@spot#update')
        def on_prices(msg):
            data = msg.get('data') if isinstance(msg, dict) else msg
            prices = data.get('prices') if isinstance(data, dict) else None
            if isinstance(prices, dict):
                for k, v in prices.items():
                    try:
                        key = str(k).upper()
                        LTP_CACHE[key] = float(v)
                        LTP_TS[key] = int(round(time.time() * 1000))
                    except Exception:
                        continue

        @sio.on('price-change')
        def on_price_change(msg):
            d = msg.get('data') if isinstance(msg, dict) else msg
            if not isinstance(d, dict):
                return
            price = d.get('p') or d.get('price') or d.get('last_price')
            sym = d.get('s') or d.get('symbol') or d.get('channel')
            if sym and price is not None:
                # normalize symbol like B-ETH_USDT -> ETHUSDT
                s = str(sym).upper()
                if s.startswith('B-'):
                    s = s[2:].replace('_','')
                else:
                    s = s.replace('_','')
                try:
                        LTP_CACHE[s] = float(price)
                        LTP_TS[s] = int(round(time.time() * 1000))
                except Exception:
                    pass

        def _run():
            backoff = 1.0
            # keep track of last connect error message to avoid log spam
            _last_connect_err = {'msg': None, 'next_backoff': None}
            while True:
                try:
                    # Only attempt connect if not already connected
                    try:
                        if not getattr(sio, 'connected', False):
                            # Use STREAM_BASE so developers can route through an MCP/proxy for testing
                            sio.connect(STREAM_BASE)
                        else:
                            # already connected; just wait for events
                            pass
                    except Exception as conn_exc:
                            # log and continue to backoff, but avoid repeating identical messages
                            try:
                                msg = str(conn_exc)
                                if _last_connect_err['msg'] != msg or _last_connect_err['next_backoff'] != backoff:
                                    print('LTP aggregator connect error, will retry in', backoff, 's ->', conn_exc)
                                    _last_connect_err['msg'] = msg
                                    _last_connect_err['next_backoff'] = backoff
                            except Exception:
                                print('LTP aggregator connect error, will retry in', backoff, 's ->', conn_exc)
                    time.sleep(backoff)
                    backoff = min(backoff * 2.0, 60.0)
                    continue

                    # wait will block until disconnect; when it returns we will loop and try reconnect
                    sio.wait()
                except Exception as e:
                    print('LTP aggregator error during wait, reconnecting in', backoff, 's ->', e)
                    time.sleep(backoff)
                    backoff = min(backoff * 2.0, 60.0)
                    continue
            # if wait() returns cleanly, reset backoff and retry
            backoff = 1.0

        t = threading.Thread(target=_run, daemon=True)
        t.start()
    except Exception as e:
        print('Failed to start LTP aggregator:', e)


def start_ltp_poller(interval: int = 1):
    """Start a background thread that periodically polls REST fallbacks for
    symbols found in user strategies to populate LTP_CACHE. This is a best-effort
    fallback when websocket subscription from server is not possible."""
    try:
        import threading

        def _short_label(sym: str) -> str:
            # Accept formats like "BINANCE:ETHUSDT", "B-ETH_USDT", "ETHUSDT"
            try:
                s = sym.strip()
                if ':' in s:
                    s = s.split(':', 1)[1]
                if s.startswith('B-'):
                    s = s[2:]
                s = s.replace('_', '')
                return s.upper()
            except Exception:
                return s.upper()

        def _run():
            global LTP_POLL_INDEX
            backoff = 1
            while True:
                try:
                    # Collect candidate symbols from UserStrategySetup table
                    syms = set()
                    try:
                        rows = db.session.query(UserStrategySetup.symbol).distinct().all()
                        for r in rows:
                            if not r or not r[0]:
                                continue
                            syms.add(_short_label(r[0]))
                    except Exception:
                        # If DB not ready, fall back to cache keys
                        syms = set(LTP_CACHE.keys())

                    if not syms:
                        # nothing to poll, sleep longer
                        time.sleep(max(5, interval))
                        continue

                    # Rotate through symbols in batches to avoid hitting rate limits
                    try:
                        sym_list = sorted(list(syms))
                        n = len(sym_list)
                        if n:
                            # compute slice to poll
                            start = LTP_POLL_INDEX % n
                            end = start + LTP_POLL_BATCH
                            slice_syms = (sym_list[start:end] if end <= n else sym_list[start:n] + sym_list[0:(end % n)])
                            # advance index for next run
                            LTP_POLL_INDEX = (start + len(slice_syms)) % n
                        else:
                            slice_syms = []
                    except Exception:
                        slice_syms = list(syms)

                    for s in slice_syms:
                        try:
                            val = fetch_ltp_from_api(s)
                            if val is not None:
                                LTP_CACHE[s] = float(val)
                                LTP_TS[s] = int(round(time.time() * 1000))
                        except Exception:
                            continue

                    time.sleep(interval)
                except Exception as e:
                    print('LTP poller error, sleeping', backoff, 's ->', e)
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 60)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
    except Exception as e:
        print('Failed to start LTP poller:', e)

# Tune this to pull more fill pages for history
ORDERS_PAGES_FILLED = 8
OPEN_SUPPRESS_AGE_DAYS = 180  # suppress very old unmatched leftovers from OPEN
MIN_CANDLES_FOR_STRATEGY = 200  # or 100 depending on how many candles your indicators need

# ------------------ Helpers ------------------
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            # If the caller expects JSON (AJAX/API) return a JSON 401 instead of redirecting
            accept = request.headers.get('Accept','')
            xreq = request.headers.get('X-Requested-With','')
            if 'application/json' in accept or xreq:
                return jsonify({'error':'unauthenticated'}), 401
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

def safe_date(ts):
    """Convert ms/seconds timestamp to YYYY-MM-DD safely, or return None if invalid."""
    try:
        if ts and ts > 0:
            # If ts looks like ms ( > year 3000 in seconds ), convert to seconds
            if ts > 1e12:
                ts = ts // 1000
            return time.strftime("%Y-%m-%d", time.gmtime(ts))
    except (OSError, ValueError, OverflowError):
        return None
    return None


def _now_ms() -> int:
    return int(round(time.time() * 1000))


def _sign(secret_key: str, body: dict) -> Tuple[str, str]:
    payload = json.dumps(body, separators=(",", ":"))
    sig = hmac.new(secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return sig, payload


def _get_signed(creds: Credentials, path: str, body: dict, timeout=15) -> Any:
    sig, payload = _sign(creds.secret_key, body)
    headers = {
        "Content-Type": "application/json",
        "X-AUTH-APIKEY": creds.api_key,
        "X-AUTH-SIGNATURE": sig
    }
    r = requests.get(API_BASE + path, headers=headers, data=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _post_signed(creds: Credentials, path: str, body: dict, timeout=30) -> Any:
    sig, payload = _sign(creds.secret_key, body)
    headers = {
        "Content-Type": "application/json",
        "X-AUTH-APIKEY": creds.api_key,
        "X-AUTH-SIGNATURE": sig
    }
    r = requests.post(API_BASE + path, headers=headers, data=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _post_signed_soft(creds: Credentials, path: str, body: dict, timeout=30) -> Optional[Any]:
    """Returns None on 422 or HTTP error; used for pagination without crashing."""
    try:
        sig, payload = _sign(creds.secret_key, body)
        headers = {
            "Content-Type": "application/json",
            "X-AUTH-APIKEY": creds.api_key,
            "X-AUTH-SIGNATURE": sig
        }
        r = requests.post(API_BASE + path, headers=headers, data=payload, timeout=timeout)
        if r.status_code == 422:
            return None
        r.raise_for_status()
        return r.json()
    except requests.HTTPError:
        return None
    except Exception:
        return None


def ms_to_utc(ms_like: Any) -> str:
    try:
        if ms_like in (None, "", 0, "0"):
            return "-"
        v = int(float(ms_like))
        if v < 10_000_000_000:
            v *= 1000
        if v <= 0:
            return "-"
        return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(v/1000))
    except Exception:
        return "-"


def _to_ms(ts_like: Any) -> float:
    try:
        v = float(ts_like)
        if v < 10_000_000_000:
            v *= 1000.0
        return v
    except Exception:
        return 0.0


def safe_float(d: dict, keys: List[str], default: float=float("nan")) -> float:
    for k in keys:
        if k in d and d[k] not in (None, "", "nan"):
            try:
                return float(d[k])
            except Exception:
                pass
    return default


def safe_str(d: dict, keys: List[str], default: str="-") -> str:
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return str(v)
    return default


def ensure_minimum_strategy_signals(min_per_setup: int = 5):
    """Ensure each UserStrategySetup has at least `min_per_setup` StrategySignal rows.
    For each setup (by id), try to backfill from PaperTrade history for that config_id
    ordered newest-first. If insufficient history exists, repeat the latest known
    active or last signal so the UI has enough rows to display.
    This is defensive and best-effort; it commits per-setup to avoid long transactions.
    """
    try:
        setups = db.session.query(UserStrategySetup).all()
    except Exception:
        return

    for us in setups:
        try:
            if not us or getattr(us, 'strategy_id', None) is None:
                continue
            # count existing signals for this (strategy_id, symbol)
            count = db.session.query(StrategySignal).filter_by(strategy_id=us.strategy_id, symbol=us.symbol).count()
            if count >= min_per_setup:
                continue

            needed = int(min_per_setup - count)

            # gather historical paper trades for this config_id, newest first
            trades = PaperTrade.query.filter_by(config_id=us.id).order_by(PaperTrade.entry_time.desc()).all()

            created = 0
            # first, convert closed trades into StrategySignal-like records (exit marked)
            for t in trades:
                if created >= needed:
                    break
                try:
                    # avoid creating duplicate signals for same entry_time
                    exists = StrategySignal.query.filter_by(strategy_id=us.strategy_id, symbol=us.symbol, entry_time=t.entry_time).first()
                    if exists:
                        continue
                    dirn = 'LONG' if (t.side == 'BUY') else 'SHORT'
                    ss = StrategySignal(strategy_id=us.strategy_id, symbol=us.symbol, direction=dirn,
                                        status=('EXITED' if t.exit_time else 'ACTIVE'),
                                        entry_price=t.entry_price, entry_time=t.entry_time,
                                        exit_price=t.exit_price, exit_time=t.exit_time)
                    db.session.add(ss)
                    db.session.commit()
                    created += 1
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                    continue

            # If still short, try to duplicate the most recent active or last signal
            if created < needed:
                try:
                    last = StrategySignal.query.filter_by(strategy_id=us.strategy_id, symbol=us.symbol).order_by(StrategySignal.entry_time.desc()).first()
                    sig = last
                    # If a PaperTrade exists for this user+config, use its fields to populate missing values
                    try:
                        pt = PaperTrade.query.filter_by(user_id=us.user_id, config_id=us.id).order_by(PaperTrade.exit_time.desc(), PaperTrade.entry_time.desc()).first()
                    except Exception:
                        pt = None

                    # prefer StrategySignal values when available
                    if sig:
                        try:
                            if getattr(sig, 'entry_price', None) is not None:
                                entry_price = sig.entry_price
                            if getattr(sig, 'exit_price', None) is not None:
                                exit_price = sig.exit_price
                            if getattr(sig, 'entry_time', None):
                                entry_time = fmt_dt(sig.entry_time)
                            if getattr(sig, 'exit_time', None):
                                exit_time = fmt_dt(sig.exit_time)
                        except Exception:
                            pass

                    # fallback to paper trade fields when signal values missing
                    if pt:
                        try:
                            if getattr(pt, 'entry_price', None) is not None and entry_price in (None,):
                                entry_price = pt.entry_price
                            if getattr(pt, 'exit_price', None) is not None and exit_price in (None,):
                                exit_price = pt.exit_price
                            if getattr(pt, 'entry_time', None) and (entry_time in (None,'')):
                                entry_time = fmt_dt(pt.entry_time)
                            if getattr(pt, 'exit_time', None) and (exit_time in (None,'')):
                                exit_time = fmt_dt(pt.exit_time)
                        except Exception:
                            pass
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                    continue
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            continue

# ------------------ Balance ------------------
def get_balance_from_api(api_key: str, secret_key: str) -> dict:
    """Futures wallets endpoint requires signed GET with body timestamp."""
    try:
        ts = _now_ms()
        body = {"timestamp": ts}
        payload = json.dumps(body, separators=(",", ":"))
        signature = hmac.new(secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
        url = API_BASE + "/exchange/v1/derivatives/futures/wallets"
        headers = {
            "Content-Type": "application/json",
            "X-AUTH-APIKEY": api_key,
            "X-AUTH-SIGNATURE": signature
        }
        r = requests.get(url, headers=headers, data=payload, timeout=12)
        data = r.json()

        if r.status_code == 200 and isinstance(data, list):
            pick = {"currency_short_name": "INR"}
            for w in data:
                if w.get("currency_short_name") == "INR":
                    pick = w; break
                if w.get("currency_short_name") == "USDT":
                    pick = w
            return {
                "connected": True,
                "balance": round(float(pick.get("balance", 0.0)), 2),
                "locked": round(float(pick.get("locked_balance", 0.0)), 2),
                "currency": pick.get("currency_short_name", "-"),
            }
        return {"connected": False, "balance": 0.0, "locked": 0.0}
    except Exception as e:
        print("Error fetching balance:", e)
        return {"connected": False, "balance": 0.0, "locked": 0.0}


# ------------------ Misc utils ------------------
def parse_to_tv_symbol(market_or_code: str) -> tuple[str, str]:
    s = market_or_code.strip()
    if ":" in s:
        tv = s
        label = s.split(":", 1)[1]
        return tv, label
    if s.startswith("B-"):
        s = s.split("-", 1)[1]
    if "_" in s:
        base, quote = s.split("_", 1)
        label = f"{base}{quote}"
        tv = f"BINANCE:{label}"
        return tv, label
    if s.isalnum() and len(s) >= 6:
        return f"BINANCE:{s}", s
    return f"BINANCE:{s.replace('_','')}", s.replace("_", "")


def fmt_dt(dt, iso: bool = False):
    """Format datetimes consistently.

    If iso=True returns an ISO8601 string with UTC tz, otherwise a
    human readable YYYY-MM-DD HH:MM:SS string. Returns None for falsy dt.
    """
    if not dt:
        return None
    try:
        if hasattr(dt, 'strftime'):
            if iso:
                try:
                    return dt.replace(tzinfo=timezone.utc).isoformat()
                except Exception:
                    return dt.isoformat()
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        return str(dt)
    except Exception:
        return None

def get_active_instruments_tv() -> list[dict]:
    try:
        url = (API_BASE + "/exchange/v1/derivatives/futures/data/"
               "active_instruments?margin_currency_short_name[]=USDT")
        r = requests.get(url, timeout=15)
        raw = r.json()
        out = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str):
                    tv, label = parse_to_tv_symbol(item)
                    out.append({"label": label, "tv": tv})
                elif isinstance(item, dict):
                    mkt = item.get("market") or item.get("symbol") or ""
                    if mkt:
                        tv, label = parse_to_tv_symbol(mkt)
                        out.append({"label": label, "tv": tv})
        return out
    except Exception as e:
        print("active_instruments error:", e)
        return []

def last_price_usdt(pair: str) -> float:
    """Quick last/mark fallback for OPEN pnl calculation."""
    try:
        # Try instrument detail first
        url = API_BASE + "/exchange/v1/derivatives/futures/data/instrument"
        r = requests.get(url, params={"pair": pair, "margin_currency_short_name": "USDT"}, timeout=10)
        det = r.json() or {}
        if isinstance(det, dict):
            inst = det.get("instrument") or (det.get("data")[0] if isinstance(det.get("data"), list) and det.get("data") else {})
            for k in ("mark_price", "last_price", "index_price"):
                v = inst.get(k)
                if v not in (None, "", 0, "0"):
                    return float(v)
    except Exception:
        pass
    try:
        end_sec = int(time.time()); start_sec = end_sec - 7*60
        r = requests.get(
            PUBLIC_BASE + "/market_data/candlesticks",
            params={"pair": pair, "from": start_sec, "to": end_sec, "resolution": "1", "pcode": "f"},
            timeout=10
        )
        rows = (r.json() or {}).get("data") or []
        return float(rows[-1]["close"]) if rows else float("nan")
    except Exception:
        return float("nan")

def usdt_inr_fx() -> float:
    try:
        r = requests.get("https://api.exchangerate.host/convert", params={"from":"USD","to":"INR"}, timeout=8)
        js = r.json()
        if isinstance(js, dict) and js.get("result"):
            return float(js["result"])
    except Exception:
        pass
    return 89.0

def role_required(role_name):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = db.session.get(User, session.get("user_id"))
            if not user or not user.role or user.role.name != role_name:
                flash("Access denied", "danger")
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)
        return wrapped
    return decorator

admin_required = role_required("admin")
moderator_required = role_required("moderator")

@app.route("/moderator/trades")
@moderator_required
def moderator_trades():
    user = db.session.get(User, session["user_id"])
    affiliates = User.query.filter_by(referred_by=user.id).all()
    # Collect trade history for each affiliate
    trades = {}
    for aff in affiliates:
        trades[aff.email] = TradeHistory.query.filter_by(user_id=aff.id).all()
    return render_template("moderator/trades.html", affiliates=affiliates, trades=trades)

@app.route("/moderator/earnings")
@moderator_required
def moderator_earnings():
    user = db.session.get(User, session["user_id"])
    earnings = ModeratorEarnings.query.filter_by(moderator_id=user.id).all()
    total_bonus = sum(e.bonus_amount for e in earnings if e.bonus_type == "referral_bonus")
    withdrawals = sum(e.bonus_amount for e in earnings if e.bonus_type == "withdrawal")
    balance = total_bonus - withdrawals
    return render_template("moderator/earnings.html",
                           earnings=earnings,
                           total_bonus=total_bonus,
                           withdrawals=withdrawals,
                           balance=balance)

# ------------------ Auth Routes ------------------
@app.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        # Check if email already exists
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash("This email is already registered. Please use a different one.", "danger")
            return redirect(url_for('signup'))

        # Create new user
        hashed_password = generate_password_hash(password)
        new_user = User(email=email, password=hashed_password, role_id=3)  # Adjust role if necessary
        db.session.add(new_user)
        db.session.commit()

        # Create paper wallet for the new user with 100000 credits
        paper_wallet = PaperWallet(user_id=new_user.id, balance=100000, realized_pnl=0, unrealized_pnl=0, available_balance=100000)
        db.session.add(paper_wallet)
        db.session.commit()

        flash("Account created successfully! Please log in.", "success")
        return redirect(url_for('login'))

    return render_template('signup.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password, password):
            # Store user_id in the session after successful login
            session['user_id'] = user.id  # Store the user's ID in the session
            flash("Login successful!", "success")
            return redirect(url_for('dashboard'))  # Redirect to the dashboard after login
        else:
            flash("Invalid email or password. Please try again.", "danger")
            return redirect(url_for('login'))

    return render_template('login.html')


# Forgot Password Route
@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']
        
        # Check if passwords match
        if new_password != confirm_password:
            flash("Passwords do not match. Please try again.", "danger")
            return redirect(url_for('forgot_password'))
        
        # Check if the new password is not empty
        if not new_password:
            flash("Password cannot be empty. Please try again.", "danger")
            return redirect(url_for('forgot_password'))
        
        # Check if user exists
        user = User.query.filter_by(email=email).first()
        if user:
            hashed_password = generate_password_hash(new_password)
            user.password = hashed_password
            
            # Commit the changes to the database
            try:
                db.session.commit()
                flash("Password updated successfully. Please log in with your new password.", "success")
                return redirect(url_for('login'))
            except Exception as e:
                flash(f"Error saving the password: {str(e)}", "danger")
                db.session.rollback()  # Rollback if an error occurs
                return redirect(url_for('forgot_password'))
        else:
            flash("Email not found. Please try again.", "danger")
            return redirect(url_for('forgot_password'))
    
    return render_template('forgot_password.html')

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# paper wallet model
@app.before_request
def ensure_paper_wallet():
    """Ensure paper wallet is created if it doesn't exist for an existing user."""
    user_id = session.get('user_id')
    
    if user_id:
        # Check if paper wallet exists for the user
        paper_wallet = PaperWallet.query.filter_by(user_id=user_id).first()
        
        if not paper_wallet:
            # If no paper wallet exists, create one with 100,000 credits
            new_wallet = PaperWallet(
                user_id=user_id, 
                balance=100000, 
                realized_pnl=0, 
                unrealized_pnl=0, 
                available_balance=100000
            )
            db.session.add(new_wallet)
            db.session.commit()
            print(f"Paper wallet created for user {user_id}.")


@app.route("/refill_wallet", methods=["POST"])
# @login_required
def refill_wallet():
    user_id = session["user_id"]
    
    # Fetch the user's paper wallet, if exists
    paper_wallet = PaperWallet.query.filter_by(user_id=user_id).first()
    
    if not paper_wallet:
        # If no paper wallet exists, create a new one
        paper_wallet = PaperWallet(
            user_id=user_id, 
            balance=100000, 
            realized_pnl=0, 
            unrealized_pnl=0, 
            available_balance=100000
        )
        db.session.add(paper_wallet)
        db.session.commit()
    
    # Update wallet to 100,000 credits if exists or after creation
    paper_wallet.balance = 100000
    paper_wallet.realized_pnl = 0
    paper_wallet.unrealized_pnl = 0
    paper_wallet.available_balance = 100000
    db.session.commit()

    # Send success response with updated data
    return jsonify({
        "success": True,
        "balance": paper_wallet.balance,
        "realized_pnl": paper_wallet.realized_pnl,
        "unrealized_pnl": paper_wallet.unrealized_pnl,
        "available_balance": paper_wallet.available_balance
    })


@app.route("/get_paper_wallet", methods=["GET"])
# @login_required
def get_paper_wallet():
    user_id = session["user_id"]
    paper_wallet = PaperWallet.query.filter_by(user_id=user_id).first()
    if paper_wallet:
        return jsonify({
            "balance": paper_wallet.balance,
            "realized_pnl": paper_wallet.realized_pnl,
            "unrealized_pnl": paper_wallet.unrealized_pnl,
            "available_balance": paper_wallet.available_balance
        })
    return jsonify({"error": "No paper wallet found."})

# Check broker connection status and balance
@app.route("/check_broker_status", methods=["GET"])
# @login_required
def check_broker_status():
    creds = Credentials.query.filter_by(user_id=session["user_id"]).first()
    if not creds:
        return jsonify({"connected": False, "message": "Broker not connected"})
    
    try:
        # Assuming a method that checks if the broker is connected
        response = get_balance_from_api(creds.api_key, creds.secret_key)
        if response["connected"]:
            return jsonify({
                "connected": True,
                "balance": response["balance"],
                "locked": response["locked"],
                "currency": response["currency"]
            })
        else:
            return jsonify({"connected": False})
    except Exception as e:
        print(f"Error checking broker status: {e}")
        return jsonify({"connected": False})

# Fetch real account data (balance, P&L, etc.)
@app.route("/get_real_account_data", methods=["GET"])
# @login_required
def get_real_account_data():
    creds = Credentials.query.filter_by(user_id=session["user_id"]).first()
    if creds:
        broker_data = get_balance_from_api(creds.api_key, creds.secret_key)
        return jsonify({
            "success": True,
            "balance": broker_data["balance"],
            "realized_pnl": broker_data["realized"],
            "unrealized_pnl": broker_data["unrealized"],
            "available_balance": broker_data["available"]
        })
    return jsonify({"success": False})


# @app.before_request
# def load_user():
#     if "user_id" in session:
#         g.user = db.session.get(User, session["user_id"])  # adjust model class if different
#     else:
#         g.user = None

# ------------------ App Pages ------------------
@app.before_request
def load_user():
    if "user_id" in session:
        g.user = db.session.get(User, session["user_id"])
        if g.user is None:
            session.clear()
            g.user = None
    else:
        g.user = None

# Toggle strategy active status (AJAX)
@app.route('/toggle_strategy/<int:config_id>', methods=['POST'])
def toggle_strategy(config_id):
    uid = session.get('user_id')
    strat = UserStrategySetup.query.filter_by(id=config_id, user_id=uid).first()
    if not strat:
        return jsonify({'success': False, 'error': 'Strategy not found'}), 404
    strat.is_active = not strat.is_active
    db.session.commit()
    # Optionally trigger background update as in start/stop
    if strat.is_active:
        def _after_start(cid):
            try:
                us = db.session.get(UserStrategySetup, cid)
                strat_obj = db.session.get(Strategy, us.strategy_id) if us else None
                sig = _compute_signal_for_user_strategy(us, strat_obj) if us and strat_obj else '-'
                rec = {'signal': sig, 'last_signal': sig, 'updated_at': int(time.time()*1000), 'symbol': us.symbol if us else ''}
                SIGNAL_CACHE[cid] = rec
                try:
                    redis_set_signal(cid, rec)
                except Exception:
                    pass
            except Exception:
                pass
        threading.Thread(target=_after_start, args=(config_id,), daemon=True).start()
    else:
        def _after_stop(cid):
            try:
                us = db.session.get(UserStrategySetup, cid)
                rec = {'signal': '-', 'last_signal': None, 'updated_at': int(time.time()*1000), 'symbol': us.symbol if us else ''}
                SIGNAL_CACHE[cid] = rec
                try:
                    redis_set_signal(cid, rec)
                except Exception:
                    pass
            except Exception:
                pass
        threading.Thread(target=_after_stop, args=(config_id,), daemon=True).start()
    return jsonify({'success': True, 'is_active': strat.is_active, 'config_id': config_id})

# Make g.user available in all templates
@app.context_processor
def inject_user():
    return dict(current_user=g.user)


@app.context_processor
def inject_stream_base():
    # Make STREAM_BASE available to client-side templates so JS can connect to the correct socket endpoint
    try:
        return dict(STREAM_BASE=STREAM_BASE)
    except Exception:
        return dict(STREAM_BASE='https://stream.coindcx.com')


@app.context_processor
def inject_mcp_cache():
    """Make a helper available in templates to read cached MCP entries by key.
    Usage in Jinja: {{ mcp_cache('path_or_key') }} which will return JSON or None.
    """
    def _get_mcp_cache(key: str):
        try:
            # prefer redis if configured
            if _redis:
                v = _redis.get(f'mcp:{key}')
                if v:
                    try:
                        return json.loads(v)
                    except Exception:
                        return v
        except Exception:
            pass
        # fallback to DB
        try:
            row = db.session.execute(text("SELECT value_json FROM mcp_cache WHERE key = :k"), {'k': f'mcp:{key}'}).fetchone()
            if row and row[0]:
                return json.loads(row[0])
        except Exception:
            pass
        return None

    return dict(mcp_cache=_get_mcp_cache)


# @app.route("/dashboard")
# @login_required
# def dashboard():
#     user = g.user
#     # fetch broker status, watchlist, etc. for this user_id
#     broker = get_broker_status(user.id)
#     watchlist = get_watchlist(user.id)
#     positions = get_positions(user.id)
#     return render_template(
#         "dashboard.html",
#         user=user,
#         broker=broker,
#         watchlist=watchlist,
#         positions=positions
#     )

@app.route("/dashboard")
# @login_required
def dashboard():
    user = g.user
    if not user:
        flash("User not found. Please log in again.", "danger")
        return redirect(url_for("login"))

    creds = Credentials.query.filter_by(user_id=user.id).first()
    broker = get_balance_from_api(creds.api_key, creds.secret_key) if creds else None
    watchlist = get_watchlist().json if creds else []
    positions = get_positions().json if creds else []
    return render_template(
        "dashboard.html",
        user=user,
        creds=creds,
        broker=broker,
        watchlist=watchlist,
        positions=positions
    )


@app.route('/strategy_signals')
def strategy_signals():
    """Render the Strategy Signals page.

    Query active UserStrategySetup rows and attach the most recent
    StrategySignal (if any) and recent PaperTrade exit reason for display.
    """
    signals = []
    notifications = []
    try:
        # helper to format datetimes consistently
        def fmt_dt(dt):
            if not dt:
                return None
            try:
                # SQLAlchemy DateTime -> Python datetime
                if hasattr(dt, 'strftime'):
                    return dt.strftime("%Y-%m-%d %H:%M:%S")
                return str(dt)
            except Exception:
                return None

        setups = UserStrategySetup.query.filter_by(is_active=True).all()
        for us in setups:
            try:
                strat = db.session.get(Strategy, us.strategy_id) if us and us.strategy_id else None

                # pick the latest signal for this strategy+symbol
                sig = StrategySignal.query.filter_by(strategy_id=us.strategy_id, symbol=us.symbol).order_by(StrategySignal.entry_time.desc()).first()

                # pick the most recent paper trade for this user+config to extract exit reason if present
                pt = PaperTrade.query.filter_by(user_id=us.user_id, config_id=us.id).order_by(PaperTrade.exit_time.desc().nulls_last(), PaperTrade.entry_time.desc()).first()

                # prefer StrategySignal values, but fallback to the most recent PaperTrade when signal is missing
                # map types: StrategySignal.direction may be LONG/SHORT while PaperTrade.side is BUY/SELL
                def map_direction(s, p):
                    if s and getattr(s, 'direction', None):
                        return s.direction
                    if p and getattr(p, 'side', None):
                        return p.side
                    return '-'

                def map_status(s, p):
                    if s and getattr(s, 'status', None):
                        return s.status
                    if p and getattr(p, 'status', None):
                        return p.status
                    return '-'

                entry_price = None
                exit_price = None
                entry_time = None
                exit_time = None

                if sig:
                    entry_price = sig.entry_price if sig.entry_price is not None else None
                    exit_price = sig.exit_price if sig.exit_price is not None else None
                    entry_time = fmt_dt(sig.entry_time) if sig.entry_time else '-'
                    exit_time = fmt_dt(sig.exit_time) if sig.exit_time else '-'
                # fallback to paper trade fields
                if (entry_price in (None,)) and pt and getattr(pt, 'entry_price', None) is not None:
                    entry_price = pt.entry_price
                if (exit_price in (None,)) and pt and getattr(pt, 'exit_price', None) is not None:
                    exit_price = pt.exit_price
                if (entry_time is None) and pt and getattr(pt, 'entry_time', None):
                    entry_time = fmt_dt(pt.entry_time)
                if (exit_time is None) and pt and getattr(pt, 'exit_time', None):
                    exit_time = fmt_dt(pt.exit_time)

                # helper: try to get realtime cached signal from redis or in-memory cache
                def get_cached_signal(uid):
                    try:
                        rec = redis_get_signal(uid) if _redis else None
                    except Exception:
                        rec = None
                    if not rec:
                        rec = SIGNAL_CACHE.get(uid)
                    return rec or {}

                row = {
                    'user_id': us.user_id,
                    'strategy': (strat.name if strat else (str(us.strategy_id) if us.strategy_id else 'Unknown')),
                    'symbol': us.symbol,
                    # generated_signal: latest runtime signal from poller/redis (BUY/SELL/HOLD/Waiting...)
                    'generated_signal': None,
                    'type': map_direction(sig, pt),
                    'status': map_status(sig, pt),
                    'entry_price': (entry_price if entry_price is not None else None),
                    'exit_price': (exit_price if exit_price is not None else None),
                    'entry_time': (entry_time if entry_time is not None else None),
                    'exit_time': (exit_time if exit_time is not None else None),
                    'trading_status': map_status(sig, pt) if map_status(sig, pt) != '-' else ('OPEN' if pt and pt.status=='OPEN' else '-'),
                    'exit_reason': (pt.exit_reason if pt and getattr(pt, 'exit_reason', None) else None)
                }
                # include realtime/generated signal from redis or in-memory cache
                try:
                    crec = redis_get_signal(us.id) if _redis else None
                except Exception:
                    crec = None
                if not crec:
                    crec = SIGNAL_CACHE.get(us.id)
                if crec:
                    row['generated_signal'] = crec.get('signal') or crec.get('last_signal')
                    # if both StrategySignal and PaperTrade missing meaningful values, use cached signal for display
                    if (not sig) and (not pt or (not getattr(pt,'entry_price',None) and not getattr(pt,'exit_price',None))):
                        csig = crec.get('signal') or crec.get('last_signal')
                        if csig:
                            row['trading_status'] = csig
                            if csig in ('BUY','SELL'):
                                row['type'] = csig
                signals.append(row)
            except Exception:
                # skip problematic setup but keep going
                continue

    except Exception:
        # fail silently and render empty list
        signals = []

    return render_template('strategy_signals.html', signals=signals, notifications=notifications)


@app.route('/api/strategy_signals')
@login_required
def api_strategy_signals():
    """JSON API: return paginated strategy signals for the current user.
    Supports filters: symbol, strategy, status, is_paper, from_ts, to_ts
    Pagination: page (1-based), per_page (max 200)
    """
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'unauthenticated'}), 401

        # query params
        page = int(request.args.get('page') or 1)
        per_page = int(request.args.get('per_page') or 50)
        per_page = max(1, min(per_page, 200))
        symbol = (request.args.get('symbol') or '').strip()
        strategy_name = (request.args.get('strategy') or '').strip()
        status = (request.args.get('status') or '').strip()
        is_paper = request.args.get('is_paper')
        from_ts = request.args.get('from')
        to_ts = request.args.get('to')

        q = db.session.query(UserStrategySetup).filter_by(is_active=True, user_id=user_id)
        if symbol:
            q = q.filter(UserStrategySetup.symbol.ilike(f"%{symbol}%"))
        if is_paper in ('0','1'):
            q = q.filter(UserStrategySetup.is_paper == (is_paper=='1'))

        total_setups = q.count()
        setups = q.order_by(UserStrategySetup.id.desc()).offset((page-1)*per_page).limit(per_page).all()

        out = []
        def fmt_dt(dt):
            if not dt:
                return None
            try:
                if hasattr(dt, 'strftime'):
                    # return ISO format (UTC); client will convert to local
                    return dt.replace(tzinfo=timezone.utc).isoformat()
                return str(dt)
            except Exception:
                return str(dt)

        for us in setups:
            try:
                strat = db.session.get(Strategy, us.strategy_id) if us and us.strategy_id else None
                # normalize symbol for matching stored signals: try TV label (ETHUSDT) so we match variants
                try:
                    _tv, _label = parse_to_tv_symbol(us.symbol or '')
                except Exception:
                    _label = (us.symbol or '').replace('BINANCE:', '').replace('B-', '').replace('_', '')
                # try exact symbol match first (handles stored 'BINANCE:ETHUSDT' or 'ETHUSDT'), then fallback to ilike
                sig = StrategySignal.query.filter(StrategySignal.strategy_id == us.strategy_id, StrategySignal.symbol == us.symbol).order_by(StrategySignal.entry_time.desc()).first()
                if not sig:
                    sig = StrategySignal.query.filter(StrategySignal.strategy_id == us.strategy_id, StrategySignal.symbol.ilike(f"%{_label}%")).order_by(StrategySignal.entry_time.desc()).first()
                if not sig:
                    # last-resort: any recent signal for this strategy (ignores symbol)
                    sig = StrategySignal.query.filter_by(strategy_id=us.strategy_id).order_by(StrategySignal.entry_time.desc()).first()

                # prefer most relevant PaperTrade: by config_id (preferred), otherwise by symbol for this user
                pt = PaperTrade.query.filter_by(user_id=us.user_id, config_id=us.id).order_by(PaperTrade.exit_time.desc(), PaperTrade.entry_time.desc()).first()
                if not pt:
                    pt = PaperTrade.query.filter_by(user_id=us.user_id, symbol=us.symbol).order_by(PaperTrade.exit_time.desc(), PaperTrade.entry_time.desc()).first()
                # refresh ORM object to ensure latest DB fields (helps after direct SQL updates in scripts)
                try:
                    if pt is not None:
                        db.session.refresh(pt)
                except Exception:
                    pass

                # prefer StrategySignal values, fallback to PaperTrade where possible
                def map_direction(s, p):
                    if s and getattr(s, 'direction', None):
                        return s.direction
                    if p and getattr(p, 'side', None):
                        return p.side
                    return None

                def map_status(s, p):
                    if s and getattr(s, 'status', None):
                        return s.status
                    if p and getattr(p, 'status', None):
                        return p.status
                    return None

                # prefer PaperTrade values (per-user) then StrategySignal; ensure proper types
                entry_price_val = None
                exit_price_val = None
                entry_time_iso = None
                exit_time_iso = None
                if pt:
                    try:
                        if getattr(pt, 'entry_price', None) is not None:
                            entry_price_val = float(pt.entry_price)
                        if getattr(pt, 'exit_price', None) is not None:
                            exit_price_val = float(pt.exit_price)
                        if getattr(pt, 'entry_time', None):
                            entry_time_iso = fmt_dt(pt.entry_time)
                        if getattr(pt, 'exit_time', None):
                            exit_time_iso = fmt_dt(pt.exit_time)
                    except Exception:
                        pass
                # fallback to StrategySignal if still empty
                if entry_price_val is None and sig and getattr(sig, 'entry_price', None) is not None:
                    try:
                        entry_price_val = float(sig.entry_price)
                    except Exception:
                        entry_price_val = None
                if exit_price_val is None and sig and getattr(sig, 'exit_price', None) is not None:
                    try:
                        exit_price_val = float(sig.exit_price)
                    except Exception:
                        exit_price_val = None
                if entry_time_iso is None and sig and getattr(sig, 'entry_time', None):
                    entry_time_iso = fmt_dt(sig.entry_time)
                if exit_time_iso is None and sig and getattr(sig, 'exit_time', None):
                    exit_time_iso = fmt_dt(sig.exit_time)

                # map final values into record (start with existing mapping helpers)
                record = {
                    'config_id': us.id,
                    'user_id': us.user_id,
                    'strategy': (strat.name if strat else (str(us.strategy_id) if us.strategy_id else 'Unknown')),
                    'symbol': us.symbol,
                    # runtime generated/cached signal from poller or redis
                    'generated_signal': None,
                    'type': map_direction(sig, pt),
                    'status': map_status(sig, pt),
                    'entry_price': entry_price_val,
                    'exit_price': exit_price_val,
                    'entry_time': entry_time_iso,
                    'exit_time': exit_time_iso,
                    'trading_status': (pt.status if pt and getattr(pt,'status',None) else (map_status(sig, pt) if map_status(sig, pt) is not None else None)),
                    'exit_reason': None,
                    'is_paper': bool(us.is_paper)
                }
                # If PaperTrade exists, prefer its side/status for type/status/trading_status where missing
                if pt:
                    try:
                        if record.get('type') in (None, '') and getattr(pt, 'side', None):
                            record['type'] = pt.side
                        if record.get('status') in (None, '') and getattr(pt, 'status', None):
                            record['status'] = pt.status
                        if not record.get('trading_status') and getattr(pt, 'status', None):
                            record['trading_status'] = pt.status
                        # prefer exit_reason from paper trade if present (some deployments may have it)
                        # Read directly from DB for this pt id to avoid any ORM caching/staleness
                        try:
                            if getattr(pt, 'id', None) is not None:
                                row = db.session.execute(text("SELECT exit_reason FROM paper_trades WHERE id = :id"), {'id': pt.id}).first()
                                if row is not None:
                                    record['exit_reason'] = row[0]
                        except Exception:
                            # fallback to in-memory attribute
                            if getattr(pt, 'exit_reason', None) is not None:
                                record['exit_reason'] = pt.exit_reason
                    except Exception:
                        pass

                # fallback to in-memory or redis cached signal if still empty
                try:
                    cached = redis_get_signal(us.id) if _redis else None
                except Exception:
                    cached = None
                if not cached:
                    cached = SIGNAL_CACHE.get(us.id)
                if cached:
                    record['generated_signal'] = cached.get('signal') or cached.get('last_signal')
                    if (record.get('type') in (None, '')) and (record.get('status') in (None, '')):
                        sigv = cached.get('signal') or cached.get('last_signal')
                        if sigv:
                            record['type'] = sigv
                            record['trading_status'] = sigv

                # If exit_reason still missing, try to fetch from TradeHistory for this user+symbol
                if not record.get('exit_reason'):
                    try:
                        th = TradeHistory.query.filter_by(user_id=us.user_id, symbol=us.symbol).order_by(TradeHistory.close_time.desc()).first()
                        if th and getattr(th, 'exit_reason', None):
                            record['exit_reason'] = th.exit_reason
                    except Exception:
                        pass

                # simple server-side filter by strategy name / status if requested
                if strategy_name and strategy_name.lower() not in (record['strategy'] or '').lower():
                    continue
                if status and status.lower() not in ((record['status'] or '')).lower():
                    continue

                out.append(record)
            except Exception:
                continue

        return jsonify({'page': page, 'per_page': per_page, 'total_setups': total_setups, 'items': out})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ------------------ User Info ------------------
def get_user_info(api_key, secret_key):
    try:
        ts = _now_ms()
        body = {"timestamp": ts}
        payload = json.dumps(body, separators=(",", ":"))
        signature = hmac.new(secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
        url = API_BASE + "/exchange/v1/users/info"
        headers = {
            "Content-Type": "application/json",
            "X-AUTH-APIKEY": api_key,
            "X-AUTH-SIGNATURE": signature
        }
        r = requests.post(url, headers=headers, data=payload, timeout=12)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print("user info error:", e)
    return None

def fetch_ltp_from_api(label: str) -> float | None:
    """Try multiple public endpoints to resolve LTP for a short label like ETHUSDT.
    Preferred: public websocket client in the browser. This function is a resilient
    REST fallback used by /ltp.
    """
    try:
        short = (label or '').upper()
        if len(short) < 6:
            return None
        # fast local cache check
        if short in LTP_CACHE:
            try:
                return float(LTP_CACHE[short])
            except Exception:
                pass
        base, quote = short[:-4], short[-4:]
        market_b = f"B-{base}_{quote}"

        # Prefer fast public Binance REST ticker first (very low latency)
        try:
            bsymbol = (short or '').upper()
            url = 'https://api.binance.com/api/v3/ticker/price'
            resp = requests.get(url, params={'symbol': bsymbol}, timeout=3)
            if resp.ok:
                js = resp.json()
                if isinstance(js, dict) and js.get('price'):
                    return float(js.get('price'))
        except Exception:
            pass

        # 1) Try public aggregated last_price endpoint (PUBLIC_BASE)
        try:
            url = PUBLIC_BASE + "/market_data/last_price"
            resp = requests.get(url, params={"pair": market_b}, timeout=6)
            js = resp.json() if resp.ok else None
            if isinstance(js, dict):
                # common keys: last_price, ltp, price
                for k in ("last_price", "ltp", "price", "last"):
                    if k in js and js[k] not in (None, ""):
                        return float(js[k])
        except Exception:
            pass

        # 2) Try public ticker endpoint
        try:
            url = PUBLIC_BASE + "/market_data/ticker"
            resp = requests.get(url, params={"pair": market_b}, timeout=6)
            if resp.ok:
                js = resp.json()
                # js may be dict or list
                if isinstance(js, dict):
                    for k in ("last_price", "ltp", "price", "last"):
                        if k in js and js[k] not in (None, ""):
                            return float(js[k])
                elif isinstance(js, list) and js:
                    # try first element
                    el = js[0]
                    if isinstance(el, dict):
                        for k in ("last_price", "ltp", "price", "last"):
                            if k in el and el[k] not in (None, ""):
                                return float(el[k])
        except Exception:
            pass

        # 3) As a last resort try the API_BASE exchange ticker (legacy) with POST
        try:
            url = API_BASE + "/exchange/ticker"
            r = requests.post(url, json={"market": market_b}, timeout=8)
            if r.ok:
                data = r.json()
                if isinstance(data, dict) and data.get("ltp"):
                    return float(data.get("ltp"))
        except Exception:
            pass

        # 3b) If server has COINDCX API credentials, try a signed GET for ticker
        try:
            if COINDCX_API_KEY and COINDCX_SECRET:
                creds = type('C', (), {'api_key': COINDCX_API_KEY, 'secret_key': COINDCX_SECRET})
                try:
                    js = _get_signed(creds, "/exchange/ticker", {"market": market_b}, timeout=8)
                    if isinstance(js, dict):
                        # older API returns {'ltp': ...}
                        if js.get('ltp') is not None:
                            return float(js.get('ltp'))
                        # or nested
                        if 'data' in js and isinstance(js['data'], dict) and js['data'].get('ltp'):
                            return float(js['data'].get('ltp'))
                except Exception:
                    pass
        except Exception:
            pass

        # 4) Final fallback: try to derive last price from candlesticks (slower)
        try:
            px = last_price_usdt(market_b)
            if px and not math.isnan(px):
                return float(px)
        except Exception:
            pass

        # 5) Try Binance public REST ticker (fast)
        try:
            bsymbol = (short or '').upper()
            # Binance expects symbol like ETHUSDT
            url = 'https://api.binance.com/api/v3/ticker/price'
            resp = requests.get(url, params={'symbol': bsymbol}, timeout=4)
            if resp.ok:
                js = resp.json()
                if isinstance(js, dict) and js.get('price'):
                    return float(js.get('price'))
        except Exception:
            pass

        # 6) Try TradingView lightweight quote (unofficial/public) as fallback
        try:
            # TradingView widget endpoints are not official; use a minimal scrape of their quote snapshot
            tv_sym = f"{short}"
            tv_url = f"https://tvc4.forexpros.com/3/3/13/13/symbols/{tv_sym}.json"
            resp = requests.get(tv_url, timeout=4)
            if resp.ok:
                js = resp.json()
                # try common nested keys
                price = None
                if isinstance(js, dict):
                    for k in ('lp','price','last'):
                        if k in js and js[k] not in (None, ''):
                            price = js[k]; break
                if price:
                    return float(price)
        except Exception:
            pass

    except Exception as e:
        print("LTP fetch error:", e)
    return None


@app.route('/ltp')
def ltp_endpoint():
    """Return LTP for a given short label (e.g. ETHUSDT) as JSON."""
    label = request.args.get('label')
    if not label:
        return jsonify({'error': 'label required'}), 400
    try:
        ltp = fetch_ltp_from_api(label)
        return jsonify({'label': label, 'ltp': ltp})
    except Exception as e:
        return jsonify({'label': label, 'ltp': None, 'error': str(e)}), 500


@app.route('/trigger_indicator/<int:config_id>', methods=['POST'])
def trigger_indicator(config_id):
    """Test-only endpoint: evaluate indicators for the given UserStrategySetup and
    run the paper trade logic (open/close) for that strategy. Returns a JSON log.

    Guard: By default only enabled if environment variable TEST_ACTIONS is '1'.
    This keeps it separate from production flows and easy to disable.
    """
    if os.environ.get('TEST_ACTIONS', '0') != '1':
        return jsonify({'error': 'Test actions disabled. Set TEST_ACTIONS=1 to enable.'}), 403

    logs = []
    try:
        us = db.session.get(UserStrategySetup, config_id)
        if not us:
            return jsonify({'error': 'strategy not found', 'config_id': config_id}), 404

        strat_obj = db.session.get(Strategy, us.strategy_id) if us.strategy_id else None

        # compute signal using existing helper
        sig = _compute_signal_for_user_strategy(us, strat_obj) if strat_obj else '-'
        logs.append(f'Computed signal: {sig}')

        # fetch candles and current price
        try:
            pair_market = tv_to_pair_market(us.symbol)
            tf = (us.timeframe or '15m').lower()
            end_dt = datetime.now(timezone.utc)
            start_dt = end_dt - timedelta(days=7)
            candles = fetch_candles(pair_market, tf, start_dt, end_dt)
            cur_px = float(candles[-1]['c']) if candles else None
            logs.append(f'Fetched {len(candles)} candles, cur_px={cur_px}')
        except Exception as e:
            logs.append(f'failed to fetch candles: {e}')
            cur_px = None

        # Use same trend confirmation logic as poller
        trend_confirmed = False
        try:
            if candles and len(candles) >= 20:
                df = pd.DataFrame([{'time': c.get('t'), 'open': c.get('o'), 'high': c.get('h'), 'low': c.get('l'), 'close': c.get('c')} for c in candles])
                closes = df['close'].astype(float)
                ma_short = closes.rolling(window=5).mean().iloc[-1]
                ma_long = closes.rolling(window=20).mean().iloc[-1]
                if sig == 'BUY' and ma_short > ma_long:
                    trend_confirmed = True
                if sig == 'SELL' and ma_short < ma_long:
                    trend_confirmed = True
                logs.append(f'trend_confirmed={trend_confirmed} ma_short={ma_short} ma_long={ma_long}')
        except Exception as e:
            logs.append(f'trend check failed: {e}')

        # process paper signal inside app context
        with app.app_context():
            before_open = PaperTrade.query.filter_by(user_id=us.user_id, config_id=us.id, status='OPEN').all()
            logs.append(f'open_trades_before={len(before_open)}')
            process_paper_signal(us, sig, cur_px, strat_obj.name if strat_obj else None, trend_confirmed)
            db.session.commit()
            after_open = PaperTrade.query.filter_by(user_id=us.user_id, config_id=us.id, status='OPEN').all()
            logs.append(f'open_trades_after={len(after_open)}')

        return jsonify({'success': True, 'logs': logs})
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({'error': str(e), 'logs': logs}), 500


@app.route('/admin/trigger_paper/<int:config_id>', methods=['POST'])
@admin_required
def admin_trigger_paper(config_id):
    """Admin-only manual trigger: evaluate the current signal for the given
    UserStrategySetup and run the paper trade handler. Returns JSON logs."""
    logs = []
    try:
        us = db.session.get(UserStrategySetup, config_id)
        if not us:
            return jsonify({'error': 'setup not found', 'config_id': config_id}), 404

        strat_obj = db.session.get(Strategy, us.strategy_id) if us.strategy_id else None
        sig = _compute_signal_for_user_strategy(us, strat_obj) if strat_obj else '-'
        logs.append(f'Computed signal: {sig}')

        # fetch candles and current price
        try:
            pair_market = tv_to_pair_market(us.symbol)
            tf = (us.timeframe or '15m').lower()
            end_dt = datetime.now(timezone.utc)
            start_dt = end_dt - timedelta(days=7)
            candles = fetch_candles(pair_market, tf, start_dt, end_dt)
            cur_px = float(candles[-1]['c']) if candles else None
            logs.append(f'Fetched {len(candles)} candles, cur_px={cur_px}')
        except Exception as e:
            logs.append(f'failed to fetch candles: {e}')
            cur_px = None

        trend_confirmed = False
        try:
            if candles and len(candles) >= 20:
                df = pd.DataFrame([{'time': c.get('t'), 'open': c.get('o'), 'high': c.get('h'), 'low': c.get('l'), 'close': c.get('c')} for c in candles])
                closes = df['close'].astype(float)
                ma_short = closes.rolling(window=5).mean().iloc[-1]
                ma_long = closes.rolling(window=20).mean().iloc[-1]
                if sig == 'BUY' and ma_short > ma_long:
                    trend_confirmed = True
                if sig == 'SELL' and ma_short < ma_long:
                    trend_confirmed = True
                logs.append(f'trend_confirmed={trend_confirmed} ma_short={ma_short} ma_long={ma_long}')
        except Exception as e:
            logs.append(f'trend check failed: {e}')

        # process inside app context
        try:
            with app.app_context():
                before_open = PaperTrade.query.filter_by(user_id=us.user_id, config_id=us.id, status='OPEN').all()
                logs.append(f'open_trades_before={len(before_open)}')
                process_paper_signal(us, sig, cur_px, strat_obj.name if strat_obj else None, trend_confirmed)
                db.session.commit()
                after_open = PaperTrade.query.filter_by(user_id=us.user_id, config_id=us.id, status='OPEN').all()
                logs.append(f'open_trades_after={len(after_open)}')
        except Exception as e:
            try:
                db.session.rollback()
            except Exception:
                pass
            logs.append(f'processing error: {e}')

        return jsonify({'success': True, 'logs': logs})
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({'error': str(e), 'logs': logs}), 500


@app.route('/admin/list_setups')
@admin_required
def admin_list_setups():
    """Return recent UserStrategySetup rows for admin UI population."""
    try:
        rows = db.session.query(UserStrategySetup).order_by(UserStrategySetup.created_at.desc()).limit(200).all()
        out = []
        for r in rows:
            out.append({
                'id': r.id,
                'user_id': r.user_id,
                'symbol': r.symbol,
                'strategy_id': r.strategy_id,
                'is_active': bool(r.is_active),
                'is_paper': bool(r.is_paper),
                'created_at': r.created_at.isoformat() if getattr(r, 'created_at', None) else None
            })
        return jsonify(out)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/admin/list_tables')
@admin_required
def admin_list_tables():
    """List all user tables and views in the SQLite database for admin UI."""
    try:
        # sqlite_master contains tables/views; adapt if using another DB
        q = text("SELECT name, type, sql FROM sqlite_master WHERE type IN ('table','view') ORDER BY name")
        res = db.session.execute(q).fetchall()
        out = []
        for r in res:
            name = r[0]
            typ = r[1]
            sql = r[2]
            out.append({'name': name, 'type': typ, 'sql': sql})
        return jsonify(out)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/admin/table_info/<table_name>')
@admin_required
def admin_table_info(table_name: str):
    """Return column info for a table/view using PRAGMA table_info (SQLite).
    The response is a list of objects: {cid, name, type, notnull, dflt_value, pk}
    """
    try:
        # validate table exists first
        q = text("SELECT name FROM sqlite_master WHERE name = :name AND type IN ('table','view')")
        found = db.session.execute(q, {'name': table_name}).fetchone()
        if not found:
            return jsonify({'error': f'table {table_name} not found'}), 404
        # use PRAGMA to get column details
        pragma_sql = text(f"PRAGMA table_info('{table_name}')")
        res = db.session.execute(pragma_sql).fetchall()
        cols = []
        for r in res:
            # Row: cid, name, type, notnull, dflt_value, pk
            cols.append({'cid': r[0], 'name': r[1], 'type': r[2], 'notnull': bool(r[3]), 'dflt_value': r[4], 'pk': bool(r[5])})
        return jsonify(cols)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/admin/db_control/delete_row', methods=['POST'])
@admin_required
def admin_db_control_delete_row():
    data = request.get_json(silent=True) or request.form
    table = (data.get('table') or '').strip()
    # Accept either {id: <val>} for backward compatibility or {column: 'colname', value: 'val'}
    id_val = data.get('id')
    col = (data.get('column') or '').strip()
    val = data.get('value')
    if not table or (id_val in (None, '') and (not col or val in (None, ''))):
        return jsonify({'error': 'table and (id or column+value) are required'}), 400
    # require advanced mode for destructive ops
    if not session.get('db_control_advanced', False):
        return jsonify({'error': 'advanced mode required to perform deletes'}), 403
    try:
        # validate table exists
        q = text("SELECT name FROM sqlite_master WHERE name = :name AND type IN ('table','view')")
        found = db.session.execute(q, {'name': table}).fetchone()
        if not found:
            return jsonify({'error': f'table {table} not found'}), 404
        # perform delete: either by id (backwards compatible) or by validated column=value
        if id_val not in (None, ''):
            del_sql = text(f'DELETE FROM "{table}" WHERE id = :val')
            res = db.session.execute(del_sql, {'val': id_val})
        else:
            # validate the column exists on the table
            pragma_sql = text(f"PRAGMA table_info('{table}')")
            cols = [r[1] for r in db.session.execute(pragma_sql).fetchall()]
            if col not in cols:
                return jsonify({'error': f'column {col} not found on table {table}'}), 400
            # Use parameterized query for the value. Column name validated above.
            del_sql = text(f'DELETE FROM "{table}" WHERE "{col}" = :val')
            res = db.session.execute(del_sql, {'val': val})
        db.session.commit()
        return jsonify({'success': True, 'deleted': res.rowcount})
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({'error': str(e)}), 500


@app.route('/ltp/batch', methods=['GET', 'POST'])
def ltp_batch():
    """Return LTPs for multiple labels.
    Accepts GET with ?labels=BTCUSDT,ETHUSDT or POST with JSON {"labels": [..]}
    """
    labels = []
    try:
        if request.method == 'POST':
            js = request.get_json(silent=True) or {}
            labels = js.get('labels') or []
        else:
            s = request.args.get('labels') or ''
            labels = [x.strip().upper() for x in s.split(',') if x.strip()]

        out = {}
        for lab in labels:
            if not lab:
                continue
            # prefer cache
            val = None
            try:
                if lab in LTP_CACHE:
                    val = float(LTP_CACHE.get(lab))
            except Exception:
                val = None
            if val is None:
                # try to fetch via fallback
                try:
                    val = fetch_ltp_from_api(lab)
                except Exception:
                    val = None
            out[lab] = val

        return jsonify({'ltps': out})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# NOTE: debug LTP cache endpoint removed for security. Use logs or
# implement a secure admin-only route if you need to inspect the cache.


@app.route("/update_api", methods=["POST"])
@login_required
def update_api():
    uid = session["user_id"]
    email = request.form["email"]; mobile = request.form["mobile"]
    api_key = request.form["api_key"]; secret_key = request.form["secret_key"]

    row = Credentials.query.filter_by(user_id=uid).first()
    if row:
        row.email = email; row.mobile = mobile
        row.api_key = api_key; row.secret_key = secret_key
    else:
        row = Credentials(user_id=uid, email=email, mobile=mobile,
                          api_key=api_key, secret_key=secret_key)
        db.session.add(row)
    db.session.commit()

    info = get_user_info(api_key, secret_key)
    if info:
        row.coindcx_id = info.get("id")
        row.first_name = info.get("first_name")
        row.last_name = info.get("last_name")
        db.session.commit()
        session["user_name"] = f"{row.first_name} {row.last_name}"

    status = get_balance_from_api(api_key, secret_key)
    if status["connected"]:
        flash(f"Broker connected. Balance: {status['balance']} | Locked: {status['locked']}", "success")
    else:
        flash("Failed to connect to broker. Check credentials.", "danger")

    return redirect(url_for("dashboard"))

@app.route("/profile")
@login_required
def profile():
    user = db.session.get(User, session["user_id"])
    creds = Credentials.query.filter_by(user_id=user.id).first()

    # fetch all trades from API
    fx_inr = usdt_inr_fx()
    raw_orders = fetch_all_orders(creds) if creds else []
    norm = [normalize_order(o) for o in raw_orders]
    _, closed = derive_from_trades(norm, fx_inr)

    total = len(closed)
    wins = sum(1 for t in closed if (_pnl_num_from_row(t) is not None) and _pnl_num_from_row(t) >= 0)
    losses = total - wins
    accuracy = round((wins / total * 100), 1) if total > 0 else 0
    net_pnl = sum((_pnl_num_from_row(t) or 0.0) for t in closed)

    return render_template("profile.html",
                           user=user,
                           creds=creds,
                           total_trades=total,
                           profitable=wins,
                           losses=losses,
                           accuracy=accuracy,
                           net_pnl=net_pnl)

@app.route("/update_api_key", methods=["POST"])
@login_required
def update_api_key():
    data = request.json
    field = data.get("field")
    value = data.get("value")

    creds = Credentials.query.filter_by(user_id=session["user_id"]).first()
    if not creds:
        creds = Credentials(user_id=session["user_id"])
        db.session.add(creds)

    if field == "apiKey":
        creds.api_key = value
    elif field == "secretKey":
        creds.secret_key = value

    db.session.commit()
    return jsonify({"success": True})


@app.route("/get_balance")
@login_required
def get_balance():
    creds = Credentials.query.filter_by(user_id=session["user_id"]).first()
    if not creds:
        return jsonify({"connected": False, "error": "no_credentials"})
    result = get_balance_from_api(creds.api_key, creds.secret_key)
    return jsonify(result)


@app.route("/get_instruments")
@login_required
def fetch_instruments():
    uid = session["user_id"]
    creds = Credentials.query.filter_by(user_id=uid).first()
    if not creds:
        return jsonify({"error": "No API credentials found!"})

    url = API_BASE + "/exchange/v1/derivatives/futures/data/active_instruments?margin_currency_short_name[]=USDT"
    try:
        response = requests.get(url, timeout=15)
        raw = response.json()
    except Exception as e:
        return jsonify({"error": f"Failed to fetch instruments: {str(e)}"})

    instruments = []
    if isinstance(raw, list):
        for symbol in raw:
            if isinstance(symbol, str):
                instruments.append({
                    "symbol": f"BINANCE:{symbol.replace('B-','').replace('_','')}",
                    "name": symbol
                })
            elif isinstance(symbol, dict):
                mkt = symbol.get("market") or symbol.get("symbol")
                if mkt:
                    instruments.append({
                        "symbol": f"BINANCE:{mkt.replace('B-','').replace('_','')}",
                        "name": mkt
                    })
    return jsonify(instruments)


# ------------------ Orders/Positions (core) ------------------
def futures_orders_paginated(creds: Credentials, status_csv: str, max_pages: int, size: int = 200) -> List[dict]:
    out: List[dict] = []
    seen: set = set()
    for p in range(1, max_pages + 1):
        body = {
            "timestamp": _now_ms(),
            "status": status_csv,
            "page": str(p),
            "size": str(size),
            "margin_currency_short_name": ["INR", "USDT"]
        }
        js = _post_signed_soft(creds, "/exchange/v1/derivatives/futures/orders", body, timeout=30)
        if not js:
            break
        rows = js if isinstance(js, list) else js.get("orders") or js.get("data") or []
        if not rows:
            break
        for o in rows:
            oid = str(o.get("id") or "")
            if not oid or oid in seen:
                continue
            seen.add(oid)
            out.append(o)
        if len(rows) < size:
            break
    return out

def fetch_all_orders(creds: Credentials, status_csv: Optional[str] = None) -> List[dict]:
    """
    Fetch all orders. If status_csv is passed, fetch only those statuses.
    Otherwise fetch open, filled, cancelled, closed.
    """
    combined: List[dict] = []

    if status_csv:
        combined += futures_orders_paginated(creds, status_csv, max_pages=ORDERS_PAGES_FILLED, size=200)
    else:
        combined += futures_orders_paginated(creds, "initial,open,partially_filled,untriggered", max_pages=1, size=200)
        combined += futures_orders_paginated(creds, "filled", max_pages=ORDERS_PAGES_FILLED, size=200)
        combined += futures_orders_paginated(creds, "cancelled,rejected,closed", max_pages=1, size=200)

    # de-dup (should already be unique)
    seen, out = set(), []
    for o in combined:
        oid = str(o.get("id") or "")
        if not oid or oid in seen:
            continue
        seen.add(oid)
        out.append(o)

    return out


def normalize_order(o: dict) -> Dict[str, Any]:
    qty_total  = safe_float(o, ["total_quantity","quantity","orig_qty"], 0.0)
    qty_filled = safe_float(o, ["filled_quantity","executed_qty","filledQuantity"], float("nan"))
    avg = safe_float(o, ["avg_price","price"], 0.0)
    lev = safe_float(o, ["leverage"], float("nan"))
    created_raw = o.get("created_at") or o.get("timestamp") or o.get("time")
    updated_raw = o.get("updated_at") or o.get("last_update_time")
    return {
        "id":         str(o.get("id")),
        "pair":       str(o.get("pair")),
        "side":       (o.get("side") or "").lower(),
        "status":     (o.get("status") or "").lower(),
        "qty":        f"{qty_total:.6f}",
        "qty_num":    float(qty_total),
        "filled":     (f"{qty_filled:.6f}" if not math.isnan(qty_filled) else "-"),
        "avg_price":  f"{avg:.6f}",
        "price_num":  0.0 if math.isnan(avg) else float(avg),
        "lev":        (f"{int(lev)}x" if not math.isnan(lev) else "-"),
        "created_at": ms_to_utc(created_raw),
        "updated_at": ms_to_utc(updated_raw),
        "created_at_raw": created_raw,
        "updated_at_raw": updated_raw,
    }

# --- Helpers for closed & open positions normalization ---
def is_finite(x: float) -> bool:
    try:
        return not (x is None or math.isnan(float(x)) or math.isinf(float(x)))
    except Exception:
        return False

def format_inr_from_usdt(pnl_usdt: float, fx_inr: float) -> str:
    if is_finite(pnl_usdt) and is_finite(fx_inr):
        return f"{(float(pnl_usdt) * float(fx_inr)):.2f} INR"
    return "-"

def normalize_closed_row(o: dict) -> dict:
    """
    Normalize a closed trade (from fills/orders API).
    """
    return {
        "id": str(o.get("id")),
        "pair": o.get("pair"),
        "side": (o.get("side") or "").upper(),
        "qty": o.get("total_quantity") or o.get("quantity") or "-",
        "entry_px": o.get("avg_entry_price") or o.get("price") or "-",
        "exit_px": o.get("avg_exit_price") or "-",
        "leverage": f"{o.get('leverage')}x" if o.get("leverage") else "-",
        "pnl": o.get("realized_pnl") or "-",
        "entry_utc": o.get("created_at") or "-",
        "exit_utc": o.get("updated_at") or "-",
    }


def normalize_position_row(p: dict) -> dict:
    side = (p.get("side") or p.get("position_side") or "").upper()
    lev  = p.get("leverage") or "-"
    qty  = p.get("quantity") or p.get("total_quantity") or p.get("position_quantity") or 0
    entry = p.get("entry_price") or p.get("avg_price") or p.get("price") or "-"
    updated = p.get("updated_at") or p.get("timestamp")
    mark = p.get("mark_price") or p.get("index_price") or "-"
    return {
        "id": str(p.get("id") or p.get("position_id") or "-"),
        "pair": p.get("pair") or p.get("market") or "-",
        "side": side,  # <-- uppercase
        "qty": f"{float(qty):.6f}" if qty not in (None,"") else "-",
        "entry_px": f"{float(entry):.6f}" if str(entry) not in ("-","") else "-",
        "mark_px": f"{float(mark):.6f}" if str(mark) not in ("-","") else "-",
        "lev": (f"{int(lev)}x" if str(lev).isdigit() else str(lev)),
        "pnl_open_inr": "-",
        "entry_at": "-",
        "updated_at": ms_to_utc(updated)
    }


def derive_from_trades(all_orders_norm: List[Dict[str, Any]], fx_inr: float) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    # Build fills list
    fills: List[Dict[str, Any]] = []
    for r in all_orders_norm:
        if r.get("status") != "filled":
            continue
        qty = float(r.get("qty_num") or 0.0)
        px  = float(r.get("price_num") or 0.0)
        if qty <= 0 or px <= 0:
            continue
        fills.append({
            "id": r["id"], "pair": r["pair"], "side": r["side"],
            "qty": qty, "price": px, "lev": r.get("lev") or "-",
            "t_ms": _to_ms(r.get("created_at_raw") or 0),
        })
    fills.sort(key=lambda x: x["t_ms"])

    closed: List[Dict[str, Any]] = []
    per_pair: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}

    for f in fills:
        pair = f["pair"]
        q = per_pair.setdefault(pair, {"buys": [], "sells": []})
        buys, sells = q["buys"], q["sells"]
        qty_rem = f["qty"]
        if f["side"] == "buy":
            while qty_rem > 0 and sells:
                s = sells[0]
                match = min(qty_rem, s["qty"])
                pnl_usdt = (s["price"] - f["price"]) * match
                closed.append({
                    "id": f"{s['id']}->{f['id']}", "pair": pair, "side": "short",
                    # expose a canonical order id (use the later fill id as representative)
                    "order_id": f["id"],
                    "qty": f"{match:.6f}", "entry_px": f"{s['price']:.6f}", "exit_px": f"{f['price']:.6f}",
                    "lev": s["lev"], "entry_ms": s["t_ms"], "exit_ms": f["t_ms"],
                    "entry_at": ms_to_utc(s["t_ms"]), "exit_at": ms_to_utc(f["t_ms"]),
                        "pnl_usdt": pnl_usdt,
                        # canonical numeric INR value (float) for programmatic use
                        "pnl_inr_value": (round(pnl_usdt * fx_inr, 2) if is_finite(pnl_usdt) and is_finite(fx_inr) else None),
                        # keep a plain numeric `pnl_inr` key for backward compatibility in places that expected a numeric field
                        "pnl_inr": (round(pnl_usdt * fx_inr, 2) if is_finite(pnl_usdt) and is_finite(fx_inr) else None),
                        # legacy formatted string kept under separate key to avoid accidental parsing elsewhere
            "pnl_inr_str": format_inr_from_usdt(pnl_usdt, fx_inr),
            # default strategy label when no provenance is known
            "strategy": "Manual",
                })
                s["qty"] -= match; qty_rem -= match
                if s["qty"] <= 1e-15: sells.pop(0)
            if qty_rem > 1e-15:
                buys.append({"id": f["id"], "price": f["price"], "qty": qty_rem, "lev": f["lev"], "t_ms": f["t_ms"]})
        else:
            while qty_rem > 0 and buys:
                b = buys[0]
                match = min(qty_rem, b["qty"])
                pnl_usdt = (f["price"] - b["price"]) * match
                closed.append({
                    "id": f"{b['id']}->{f['id']}", "pair": pair, "side": "long",
                    "order_id": f["id"],
                    "qty": f"{match:.6f}", "entry_px": f"{b['price']:.6f}", "exit_px": f"{f['price']:.6f}",
                    "lev": b["lev"], "entry_ms": b["t_ms"], "exit_ms": f["t_ms"],
                    "entry_at": ms_to_utc(b["t_ms"]), "exit_at": ms_to_utc(f["t_ms"]),
                    "pnl_usdt": pnl_usdt,
                    "pnl_inr_value": (round(pnl_usdt * fx_inr, 2) if is_finite(pnl_usdt) and is_finite(fx_inr) else None),
                    "pnl_inr": (round(pnl_usdt * fx_inr, 2) if is_finite(pnl_usdt) and is_finite(fx_inr) else None),
                    "pnl_inr_str": format_inr_from_usdt(pnl_usdt, fx_inr),
                    # default strategy label when no provenance is known
                    "strategy": "Manual",
                })
                b["qty"] -= match; qty_rem -= match
                if b["qty"] <= 1e-15: buys.pop(0)
            if qty_rem > 1e-15:
                sells.append({"id": f["id"], "price": f["price"], "qty": qty_rem, "lev": f["lev"], "t_ms": f["t_ms"]})

    # Build OPEN (aggregate VWAP) — suppress very old leftovers
    open_rows: List[Dict[str, Any]] = []
    now_ms = _now_ms()
    cutoff_ms = now_ms - OPEN_SUPPRESS_AGE_DAYS * 24 * 60 * 60 * 1000

    for pair, q in per_pair.items():
        if q["buys"]:
            tot_qty = sum(x["qty"] for x in q["buys"])
            if tot_qty > 1e-12:
                first_t = min(x["t_ms"] for x in q["buys"])
                if first_t >= cutoff_ms:
                    vwap = sum(x["qty"]*x["price"] for x in q["buys"]) / tot_qty
                    lev0 = q["buys"][0]["lev"]
                    mark = last_price_usdt(pair)
                    pnl_usdt = (mark - vwap) * tot_qty if is_finite(mark) else float("nan")
                    open_rows.append({
                        "id": q["buys"][0]["id"], "pair": pair, "side": "long",
                        "order_id": q["buys"][0]["id"],
                        "qty": f"{tot_qty:.6f}", "entry_px": f"{vwap:.6f}",
                        "mark_px": f"{(mark if is_finite(mark) else 0.0):.6f}" if is_finite(mark) else "-",
                        "lev": lev0,
                        "pnl_open_usdt": (pnl_usdt if is_finite(pnl_usdt) else None),
                            "pnl_open_inr_value": (round(pnl_usdt * fx_inr, 2) if is_finite(pnl_usdt) and is_finite(fx_inr) else None),
                            "pnl_open_inr": (round(pnl_usdt * fx_inr, 2) if is_finite(pnl_usdt) and is_finite(fx_inr) else None),
                            "pnl_open_inr_str": format_inr_from_usdt(pnl_usdt, fx_inr),
                        "entry_at": ms_to_utc(first_t), "updated_at": ms_to_utc(max(x["t_ms"] for x in q["buys"])),
                        # default strategy when none is available
                        "strategy": "Manual",
                    })
        if q["sells"]:
            tot_qty = sum(x["qty"] for x in q["sells"])
            if tot_qty > 1e-12:
                first_t = min(x["t_ms"] for x in q["sells"])
                if first_t >= cutoff_ms:
                    vwap = sum(x["qty"]*x["price"] for x in q["sells"]) / tot_qty
                    lev0 = q["sells"][0]["lev"]
                    mark = last_price_usdt(pair)
                    pnl_usdt = (vwap - mark) * tot_qty if is_finite(mark) else float("nan")
                    open_rows.append({
                        "id": q["sells"][0]["id"], "pair": pair, "side": "short",
                        "order_id": q["sells"][0]["id"],
                        "qty": f"{tot_qty:.6f}", "entry_px": f"{vwap:.6f}",
                        "mark_px": f"{(mark if is_finite(mark) else 0.0):.6f}" if is_finite(mark) else "-",
                        "lev": lev0,
                        "pnl_open_usdt": (pnl_usdt if is_finite(pnl_usdt) else None),
                            "pnl_open_inr_value": (round(pnl_usdt * fx_inr, 2) if is_finite(pnl_usdt) and is_finite(fx_inr) else None),
                            "pnl_open_inr": (round(pnl_usdt * fx_inr, 2) if is_finite(pnl_usdt) and is_finite(fx_inr) else None),
                            "pnl_open_inr_str": format_inr_from_usdt(pnl_usdt, fx_inr),
                        "entry_at": ms_to_utc(first_t), "updated_at": ms_to_utc(max(x["t_ms"] for x in q["sells"])),
                        # default strategy when none is available
                        "strategy": "Manual",
                    })

    open_rows.sort(key=lambda r: (r["pair"], r["side"]))
    closed.sort(key=lambda r: r["exit_ms"], reverse=True)
    return open_rows, closed

def format_inr(value):
    try:
        value = float(value)
        return f"₹ {value:,.2f}"
    except Exception:
        return f"₹ {value}"

# Register the filter with Jinja
app.jinja_env.filters['format_inr'] = format_inr

def _pnl_num_from_row(row):
    """Return numeric PnL in INR for a trade row if possible, else None."""
    try:
        if not row:
            return None
        # prefer explicit numeric field
        if isinstance(row, dict) and row.get('pnl_inr_value') is not None:
            return float(row.get('pnl_inr_value'))
        # fallback to numeric pnl_inr field (could be already numeric)
        if isinstance(row, dict) and row.get('pnl_inr') is not None:
            v = row.get('pnl_inr')
        else:
            v = row
        if v is None:
            return None
        s = str(v)
        # strip currency symbols and text
        s = s.replace('₹','').replace('$','').replace('INR','').replace(',','').strip()
        if s == '':
            return None
        return float(s)
    except Exception:
        return None

def fetch_positions_api(creds: Credentials) -> List[dict]:
    """Authoritative OPEN positions from /positions endpoint; paginated; returns list of dicts."""
    pos_all: List[dict] = []
    page = 1
    while True:
        body = {
            "timestamp": _now_ms(),
            "page": str(page),
            "size": "200",
            "margin_currency_short_name": ["USDT"]   # 👈 FIXED
        }
        js = _post_signed_soft(creds, "/exchange/v1/derivatives/futures/positions", body, timeout=30)
        if not js:
            break
        rows = js if isinstance(js, list) else js.get("positions") or js.get("data") or []
        if not rows:
            break
        pos_all.extend(rows)
        if len(rows) < 200:
            break
        page += 1
    return pos_all

def normalize_position_row(p: dict) -> dict:
    # Coindcx position fields vary; map safely
    side = (p.get("side") or p.get("position_side") or "").lower()
    lev  = p.get("leverage") or "-"
    qty  = p.get("quantity") or p.get("total_quantity") or p.get("position_quantity") or 0
    entry = p.get("entry_price") or p.get("avg_price") or p.get("price") or "-"
    updated = p.get("updated_at") or p.get("timestamp")
    # live mark (if provided)
    mark = p.get("mark_price") or p.get("index_price") or "-"
    return {
        "id": str(p.get("id") or p.get("position_id") or "-"),
        "pair": p.get("pair") or p.get("market") or "-",
        "side": side,
        "qty": f"{float(qty):.6f}" if qty not in (None,"") else "-",
        "entry_px": f"{float(entry):.6f}" if isinstance(entry,(float,int,str)) and str(entry) not in ("-","") else "-",
        "mark_px": f"{float(mark):.6f}" if isinstance(mark,(float,int,str)) and str(mark) not in ("-","") else "-",
        "lev": (f"{int(lev)}x" if isinstance(lev,(int,float,str)) and str(lev).isdigit() else str(lev)),
        "pnl_open_inr": "-",  # we add below with FX
        "entry_at": "-", "updated_at": ms_to_utc(updated)
    }

def tv_to_pair_market(tv: str) -> str:
    # "BINANCE:ETHUSDT" -> "B-ETH_USDT"
    try:
        sym = tv.split(":", 1)[1]  # ETHUSDT
        base, quote = sym[:-4], sym[-4:]
        return f"B-{base}_{quote}"
    except Exception:
        return "B-ETH_USDT"

def timeframe_to_resolution(tf: str) -> str:
    """
    Map timeframe string (like '1m','15m','1h','2h','4h','8h','1d','1w') to resolution codes
    used by the Coindcx public candles API.
    If tf is not found or is 'Auto', default to '15' (15m).
    """
    m = {
        "1m": "1",
        "5m": "5",
        "15m": "15",
        "1h": "60",
        "2h": "120",
        "4h": "240",
        "8h": "480",
        "12h": "720",  # if needed
        "1d": "D",
        "1w": "W",
    }
    tf_key = tf.lower()
    if tf_key == "auto":
        return m.get("15m")  # default resolution for auto: use 15m
    return m.get(tf_key, m["15m"])

def naive_backtest_pnl_inr(pair_market: str, timeframe: str, start_dt, end_dt, margin_in_inr: float, leverage: int) -> tuple[float,float,dict]:
    """
    Super-light ‘backtest’: buy-and-hold within range with leverage multiplier.
    - Fetch first and last candle close and compute return.
    - Convert INR↔USDT using usdt_inr_fx() to report both.
    """
    try:
        start_sec = int(time.mktime(time.strptime(start_dt.strftime("%Y-%m-%d")+" 00:00:00","%Y-%m-%d %H:%M:%S")))
        end_sec   = int(time.mktime(time.strptime(end_dt.strftime("%Y-%m-%d")+" 23:59:59","%Y-%m-%d %H:%M:%S")))
        res = timeframe_to_resolution(timeframe)

        r = requests.get(
            PUBLIC_BASE + "/market_data/candlesticks",
            params={"pair": pair_market, "from": start_sec, "to": end_sec, "resolution": res, "pcode": "f"},
            timeout=15
        )
        rows = (r.json() or {}).get("data") or []
        if not rows:
            return 0.0, 0.0, {"note":"no candles returned"}

        open_px = float(rows[0]["open"])
        close_px = float(rows[-1]["close"])
        ret = (close_px - open_px) / open_px  # simple return

        fx = usdt_inr_fx()
        usdt_margin = margin_in_inr / fx if fx > 0 else 0.0
        pnl_usdt = usdt_margin * ret * max(leverage, 1)
        pnl_inr = pnl_usdt * fx

        metrics = {
            "open_px": open_px, "close_px": close_px,
            "return_pct": round(ret*100, 2),
            "leverage": leverage, "margin_in_inr": margin_in_inr,
            "candles": len(rows)
        }
        return pnl_inr, pnl_usdt, metrics
    except Exception as e:
        return 0.0, 0.0, {"error": str(e)}

# ------------------ Watchlist APIs ------------------
@app.route("/add_watchlist", methods=["POST"])
@login_required
def add_watchlist():
    symbol = request.json.get("symbol")
    if not symbol:
        return jsonify({"error": "symbol required"}), 400
    uid = session["user_id"]
    tv, label = parse_to_tv_symbol(symbol)
    if not Watchlist.query.filter_by(user_id=uid, symbol=tv).first():
        db.session.add(Watchlist(user_id=uid, symbol=tv))
        db.session.commit()
    return jsonify({"message": "Added", "symbol": tv, "label": label})

@app.route("/remove_watchlist", methods=["POST"])
@login_required
def remove_watchlist():
    symbol = request.json.get("symbol")
    uid = session["user_id"]
    item = Watchlist.query.filter_by(user_id=uid, symbol=symbol).first()
    if item:
        db.session.delete(item)
        db.session.commit()
    return jsonify({"message": "Removed"})

@app.route("/get_watchlist")
@login_required
def get_watchlist():
    uid = session["user_id"]
    wl = Watchlist.query.filter_by(user_id=uid).all()
    out = []
    for w in wl:
        tv, label = parse_to_tv_symbol(w.symbol)
        ltp = fetch_ltp_from_api(label)
        out.append({"symbol": tv, "label": label, "ltp": ltp})
    return jsonify(out)

# ------------------ Strategy Builder ------------------
@app.route("/admin/strategies", methods=["GET", "POST"], endpoint="manage_strategies")
# @admin_required
def manage_strategies():
    form = StrategyForm()

    if request.method == "POST":
        strategy_id = request.form.get("strategy_id")

        if strategy_id:  # UPDATE
            s = Strategy.query.get_or_404(strategy_id)
            s.name = form.name.data
            s.description = form.description.data
            s.video_url = form.video_url.data
            s.signals = form.signals.data
            s.difficulty = form.difficulty.data
            s.timeframe = form.timeframe.data
            s.gain = form.gain.data
            s.users = form.users.data
            s.is_active = form.is_active.data
            flash(f"Strategy '{s.name}' updated!", "success")
        else:  # ADD NEW
            s = Strategy(
                name=form.name.data,
                description=form.description.data,
                video_url=form.video_url.data,
                signals=form.signals.data,
                difficulty=form.difficulty.data,
                timeframe=form.timeframe.data,
                gain=form.gain.data,
                users=form.users.data,
                is_active=form.is_active.data,
            )
            db.session.add(s)
            flash("New strategy added!", "success")

        db.session.commit()
        return redirect(url_for("manage_strategies"))

    strategies = Strategy.query.all()
    return render_template("admin/manage_strategies.html", form=form, strategies=strategies)


# ------------------ Public Strategies Page ------------------
@app.route("/strategies", endpoint="public_strategies")
# @login_required
def show_strategies():
    user = db.session.get(User, session["user_id"])
    creds = Credentials.query.filter_by(user_id=user.id).first()
    strategies = Strategy.query.filter_by(is_active=True).all()
    return render_template(
        "strategy.html",
        strategies=strategies,
        user=user,
        creds=creds
    )

# ------------------ Admin Required Decorator ------------------
def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        user = db.session.get(User, session["user_id"])

        # ✅ Check by role name instead of a missing is_admin field
        if not user or not user.role or user.role.name.lower() != "admin":
            flash("Admin access required!", "danger")
            return redirect(url_for("dashboard"))

        return view(*args, **kwargs)
    return wrapped

# Admin Panel Route
@app.route("/moderator/affiliate_summary", endpoint="affiliate_summary")
@login_required
def affiliate_summary():
    # Your code to render affiliate summary page
    return render_template('affiliate_summary.html')

@app.route("/moderator/my_earnings", endpoint="my_earnings")
@login_required
def earnings_summary():
    # Your code to render affiliate summary page
    return render_template('my_earnings.html')

# ========= BACKTEST HELPERS (MA + RSI) =========
def fetch_candles(pair_market: str, timeframe: str, start_dt, end_dt) -> list[dict]:
    """Return list of {time, open, high, low, close} rows (UTC seconds)."""
    # Try primary Coindcx public candles first
    try:
        res = timeframe_to_resolution(timeframe)
        start_sec = int(time.mktime(time.strptime(start_dt.strftime("%Y-%m-%d")+" 00:00:00","%Y-%m-%d %H:%M:%S")))
        end_sec   = int(time.mktime(time.strptime(end_dt.strftime("%Y-%m-%d")+" 23:59:59","%Y-%m-%d %H:%M:%S")))
        r = requests.get(
            PUBLIC_BASE + "/market_data/candlesticks",
            params={"pair": pair_market, "from": start_sec, "to": end_sec, "resolution": res, "pcode": "f"},
            timeout=12
        )
        rows = (r.json() or {}).get("data") or []
        if rows:
            out = []
            for x in rows:
                out.append({
                    "t": int(x["time"]),   # seconds
                    "o": float(x["open"]),
                    "h": float(x["high"]),
                    "l": float(x["low"]),
                    "c": float(x["close"]),
                })
            return out
    except Exception:
        pass

    # Fallback: try Binance public klines for the same symbol
    try:
        bc = fetch_candles_binance(pair_market, timeframe, start_dt, end_dt)
        if bc:
            return bc
    except Exception:
        pass

    # Last resort: return empty list so callers know data is unavailable
    return []


def _pair_to_binance_symbol(pair_market: str) -> str:
    """Convert pair_market like 'B-ETH_USDT' or 'BINANCE:ETHUSDT' to Binance symbol like 'ETHUSDT'."""
    try:
        s = pair_market or ''
        if ':' in s:
            s = s.split(':',1)[1]
        if s.startswith('B-'):
            s = s[2:]
        s = s.replace('_', '').replace('/', '').upper()
        return s
    except Exception:
        return pair_market


def timeframe_to_binance_interval(tf: str) -> str:
    """Map timeframe to Binance interval strings (best-effort)."""
    if not tf:
        return '15m'
    t = str(tf).lower()
    # normalized forms
    mapping = {
        '1': '1m', '1m': '1m', '5m': '5m', '15': '15m', '15m': '15m',
        '30m': '30m', '1h': '1h', '60': '1h', '2h': '2h', '120': '2h',
        '4h': '4h', '240': '4h', '1d': '1d', 'd': '1d', '1w': '1w'
    }
    return mapping.get(t, '15m')


def fetch_candles_binance(pair_market: str, timeframe: str, start_dt, end_dt) -> list[dict]:
    """Fetch klines from Binance REST API and normalize them.
    Returns list of dicts with keys t (seconds), o/h/l/c floats.
    """
    try:
        symbol = _pair_to_binance_symbol(pair_market)
        interval = timeframe_to_binance_interval(timeframe)
        start_ms = int(time.mktime(start_dt.timetuple()) * 1000)
        end_ms = int(time.mktime(end_dt.timetuple()) * 1000)
        url = f'https://api.binance.com/api/v3/klines'
        params = {'symbol': symbol, 'interval': interval, 'startTime': start_ms, 'endTime': end_ms, 'limit': 1000}
        resp = requests.get(url, params=params, timeout=8)
        if not resp.ok:
            return []
        arr = resp.json() or []
        out = []
        for it in arr:
            # Binance kline: [openTime, open, high, low, close, ...]
            try:
                t_ms = int(it[0])
                out.append({'t': int(t_ms/1000), 'o': float(it[1]), 'h': float(it[2]), 'l': float(it[3]), 'c': float(it[4])})
            except Exception:
                continue
        return out
    except Exception:
        return []

# SMA - Simple Moving Average
def sma(series: list[float], window: int) -> list[float]:
    out, s = [], 0.0
    q = collections.deque()
    for v in series:
        q.append(v); s += v
        if len(q) > window:
            s -= q.popleft()
        out.append(s/len(q) if q else float("nan"))
    return out

# RSI - Relative Strength Index
def rsi(series: list[float], period: int = 14) -> list[float]:
    gains, losses = 0.0, 0.0
    rsis = [float("nan")] * len(series)
    for i in range(1, len(series)):
        ch = series[i] - series[i-1]
        gain = max(ch, 0.0); loss = -min(ch, 0.0)
        if i <= period:
            gains += gain; losses += loss
            if i == period:
                avg_gain = gains/period
                avg_loss = losses/period
                rs = (avg_gain / avg_loss) if avg_loss > 0 else float("inf")
                rsis[i] = 100 - (100/(1+rs))
        else:
            avg_gain = (avg_gain*(period-1) + gain)/period
            avg_loss = (avg_loss*(period-1) + loss)/period
            rs = (avg_gain / avg_loss) if avg_loss > 0 else float("inf")
            rsis[i] = 100 - (100/(1+rs))
    return rsis

# MACD - Moving Average Convergence Divergence
def macd(series: pd.Series, short_span: int = 12, long_span: int = 26, signal_span: int = 9) -> pd.Series:
    """MACD and Signal Line"""
    ema_short = series.ewm(span=short_span, adjust=False).mean()
    ema_long = series.ewm(span=long_span, adjust=False).mean()
    macd_line = ema_short - ema_long
    macd_signal = macd_line.ewm(span=signal_span, adjust=False).mean()
    return macd_line, macd_signal

# Stochastic Oscillator
def stochastic_oscillator(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Calculates the Stochastic Oscillator (Fast %K)"""
    # Using 'l' for low price (if 'low' doesn't exist in the DataFrame)
    low_min = df['low'].rolling(window=window).min()
    high_max = df['high'].rolling(window=window).max()
    
    # Calculate the %K (Fast Stochastic Oscillator)
    stoch_k = 100 * ((df['close'] - low_min) / (high_max - low_min))
    
    return stoch_k


# Bollinger Bands
def bollinger_bands(series: pd.Series, window: int = 20, num_std: int = 2) -> tuple:
    sma_ = series.rolling(window=window).mean()
    rolling_std = series.rolling(window=window).std()
    upper_band = sma_ + (rolling_std * num_std)
    lower_band = sma_ - (rolling_std * num_std)
    return upper_band, sma_, lower_band

# Calculate ATR (Average True Range)
def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """
    Calculates the Average True Range (ATR) for a given DataFrame.
    ATR measures market volatility.
    """
    high_low = df['h'] - df['l']
    high_close = (df['h'] - df['close'].shift()).abs()
    low_close = (df['l'] - df['close'].shift()).abs()
    
    tr = pd.concat([high_low, high_close, low_close], axis=1)
    tr = tr.max(axis=1)
    
    return tr.rolling(window=window).mean()

# unction to check for a choppy market using Bollinger Bands
def is_choppy(df: pd.DataFrame, threshold: float = 0.015) -> pd.Series:
    """
    Identifies a choppy market by checking if Bollinger Bands are narrow.
    
    A lower threshold means the market is considered choppy only when volatility is very low.
    
    Args:
        df: DataFrame with 'close' price data.
        threshold: The threshold for the normalized band width.
        
    Returns:
        A boolean Series, True where the market is considered choppy.
        # Optionally start the MCP worker in-process (useful for local dev); set START_MCP_WORKER=1
        if os.environ.get('START_MCP_WORKER','0') == '1':
            try:
                from mcp_worker import start_mcp_worker
                app.before_first_request(lambda: start_mcp_worker())
            except Exception:
                pass
    """
    upper, middle, lower = bollinger_bands(df['close'])
    normalized_bandwidth = (upper - lower) / middle
    return normalized_bandwidth < threshold



# Intraday Strategy
def intraday_strategy(df: pd.DataFrame) -> pd.DataFrame:
    """Intraday Strategy using RSI, EMA"""
    closes = df['close']
    rsi14 = rsi(closes, 14)
    ema21 = sma(closes, 21)
    ema50 = sma(closes, 50)
    macd_line, macd_signal = macd(closes)

    # Convert lists to Pandas Series for element-wise comparisons
    rsi14_series = pd.Series(rsi14, index=df.index)
    ema21_series = pd.Series(ema21, index=df.index)
    ema50_series = pd.Series(ema50, index=df.index)
    macd_line_series = pd.Series(macd_line, index=df.index)
    macd_signal_series = pd.Series(macd_signal, index=df.index)

    # Buy signal: RSI > 35, EMA21 > EMA50, MACD Line > MACD Signal
    df['buy_signal'] = (rsi14_series > 35) & (ema21_series > ema50_series) & (macd_line_series > macd_signal_series)
    
    # Sell signal: RSI < 70, EMA21 < EMA50, MACD Line < MACD Signal
    df['sell_signal'] = (rsi14_series < 70) & (ema21_series < ema50_series) & (macd_line_series < macd_signal_series)

    return df[['buy_signal', 'sell_signal']]

# Scalping Strategy
def scalping_strategy(df: pd.DataFrame) -> pd.DataFrame:
    """Scalping Strategy using Stochastic Oscillator and EMA"""
    stoch = stochastic_oscillator(df)
    ema21 = sma(df['close'], 21)
    ema50 = sma(df['close'], 50)

    # Convert lists to Pandas Series for element-wise comparisons
    stoch_series = pd.Series(stoch, index=df.index)
    ema21_series = pd.Series(ema21, index=df.index)
    ema50_series = pd.Series(ema50, index=df.index)

    # Buy signal: Stochastic > 80, EMA21 > EMA50
    df['buy_signal'] = (stoch_series > 80) & (ema21_series > ema50_series)
    
    # Sell signal: Stochastic < 20, EMA21 < EMA50
    df['sell_signal'] = (stoch_series < 20) & (ema21_series < ema50_series)

    return df[['buy_signal', 'sell_signal']]

# Swing Strategy
def swing_strategy(df: pd.DataFrame) -> pd.DataFrame:
    """Swing Strategy using MACD and SMA"""
    closes = df['close']
    macd_line, macd_signal = macd(closes)
    sma200 = sma(closes, 200)

    # Convert lists to Pandas Series for element-wise comparisons
    macd_line_series = pd.Series(macd_line, index=df.index)
    macd_signal_series = pd.Series(macd_signal, index=df.index)
    sma200_series = pd.Series(sma200, index=df.index)

    # Buy signal: MACD Line > MACD Signal, Price > 200 SMA
    df['buy_signal'] = (macd_line_series > macd_signal_series) & (closes > sma200_series)

    # Sell signal: MACD Line < MACD Signal, Price < 200 SMA
    df['sell_signal'] = (macd_line_series < macd_signal_series) & (closes < sma200_series)

    return df[['buy_signal', 'sell_signal']]

# Short-Term Strategy
def short_term_strategy(df: pd.DataFrame) -> pd.DataFrame:
    """Short-term Strategy using Bollinger Bands and RSI"""
    closes = df['close']
    upper_band, middle_band, lower_band = bollinger_bands(closes)
    rsi14 = rsi(closes, 14)

    # Convert lists to Pandas Series for element-wise comparisons
    upper_band_series = pd.Series(upper_band, index=df.index)
    lower_band_series = pd.Series(lower_band, index=df.index)
    rsi14_series = pd.Series(rsi14, index=df.index)

    # Buy signal: Price crosses below lower band and RSI > 30
    df['buy_signal'] = (closes < lower_band_series) & (rsi14_series > 30)

    # Sell signal: Price crosses above upper band and RSI < 70
    df['sell_signal'] = (closes > upper_band_series) & (rsi14_series < 70)

    return df[['buy_signal', 'sell_signal']]

# Long-Term Strategy
def long_term_strategy(df: pd.DataFrame) -> pd.DataFrame:
    """Long-term Strategy using MACD and EMA"""
    closes = df['close']
    macd_line, macd_signal = macd(closes)
    ema50 = sma(closes, 50)

    # Convert lists to Pandas Series for element-wise comparisons
    macd_line_series = pd.Series(macd_line, index=df.index)
    macd_signal_series = pd.Series(macd_signal, index=df.index)
    ema50_series = pd.Series(ema50, index=df.index)

    # Buy signal: MACD Line > MACD Signal and Price above EMA50
    df['buy_signal'] = (macd_line_series > macd_signal_series) & (closes > ema50_series)

    # Sell signal: MACD Line < MACD Signal and Price below EMA50
    df['sell_signal'] = (macd_line_series < macd_signal_series) & (closes < ema50_series)

    return df[['buy_signal', 'sell_signal']]

def twin_range_filter_strategy(df: pd.DataFrame, source_col: str = 'close', per1: int = 27, mult1: float = 1.6,
                               per2: int = 55, mult2: float = 2.0) -> pd.DataFrame:
    """
    Port of 'Twin Range Filter' PineScript -> Pandas. Produces buy/sell signals
    via columns 'buy_signal' and 'sell_signal'.
    """
    df = df.copy()
    if source_col not in df.columns:
        raise ValueError(f"Source column '{source_col}' missing from DataFrame")

    src = df[source_col].astype(float)

    def smoothrng(x: pd.Series, t: int, m: float) -> pd.Series:
        wper = t * 2 - 1
        avrng = x.diff().abs().ewm(span=t, adjust=False).mean()
        smr = avrng.ewm(span=wper, adjust=False).mean() * m
        return smr

    smrng1 = smoothrng(src, per1, mult1)
    smrng2 = smoothrng(src, per2, mult2)
    smrng = (smrng1 + smrng2) / 2.0

    # range filter logic
    filt = pd.Series(index=df.index, dtype=float)
    # initialize filt[0] = src[0]
    if len(src) > 0:
        filt.iloc[0] = src.iloc[0]
    for i in range(1, len(src)):
        x = src.iloc[i]
        prev = filt.iloc[i-1]
        r = smrng.iloc[i] if not pd.isna(smrng.iloc[i]) else smrng.iloc[i-1] if i-1>=0 else 0.0
        # translate the nested ternary logic from Pine
        if x > prev:
            if (x - r) < prev:
                filt.iloc[i] = prev
            else:
                filt.iloc[i] = x - r
        else:
            if (x + r) > prev:
                filt.iloc[i] = prev
            else:
                filt.iloc[i] = x + r

    # upward / downward counts
    upward = (filt > filt.shift(1)).astype(int).groupby((filt <= filt.shift(1)).cumsum()).cumcount()+1
    downward = (filt < filt.shift(1)).astype(int).groupby((filt >= filt.shift(1)).cumsum()).cumcount()+1
    # fill zeros where not increasing/decreasing
    upward = upward.where(filt > filt.shift(1), 0)
    downward = downward.where(filt < filt.shift(1), 0)

    hband = filt + smrng
    lband = filt - smrng

    # long/short conditions
    src_prev = src.shift(1)
    longCond = ((src > filt) & (src > src_prev) & (upward > 0)) | ((src > filt) & (src < src_prev) & (upward > 0))
    shortCond = ((src < filt) & (src < src_prev) & (downward > 0)) | ((src < filt) & (src > src_prev) & (downward > 0))

    # CondIni: carry previous state (0 -> neutral, 1 -> long, -1 -> short)
    condini = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        if longCond.iloc[i]:
            condini.iloc[i] = 1
        elif shortCond.iloc[i]:
            condini.iloc[i] = -1
        else:
            condini.iloc[i] = condini.iloc[i-1]

    # Entry logic: flip when current cond and previous CondIni opposite
    long_entries = (longCond) & (condini.shift(1) == -1)
    short_entries = (shortCond) & (condini.shift(1) == 1)

    df['filt'] = filt
    df['hband'] = hband
    df['lband'] = lband
    df['buy_signal'] = long_entries.fillna(False)
    df['sell_signal'] = short_entries.fillna(False)
    return df


def ai_strategy(df: pd.DataFrame) -> pd.DataFrame:
    """AI-style heuristic strategy combining simple chart-patterns,
    support/resistance retests and common candlestick patterns.

    Produces columns:
      - buy_signal (bool)
      - sell_signal (bool)
      - entry_reason (str) optional human-readable reason for entry
      - exit_reason (str) optional human-readable reason for exit
    """
    df = df.copy()
    # Ensure required columns
    for col in ('open', 'high', 'low', 'close'):
        if col not in df.columns:
            df[col] = 0.0

    # Candle geometry
    body = (df['close'] - df['open']).abs()
    body_signed = (df['close'] - df['open'])
    upper_shad = df['high'] - df[['open', 'close']].max(axis=1)
    lower_shad = df[['open', 'close']].min(axis=1) - df['low']

    # Simple candlestick pattern detectors
    is_hammer = (lower_shad > 2 * body) & (upper_shad < 0.5 * body) & (body / (df['high'] - df['low'] + 1e-9) < 0.4) & (body_signed > 0)
    is_hanging_man = (lower_shad > 2 * body) & (upper_shad < 0.5 * body) & (body / (df['high'] - df['low'] + 1e-9) < 0.4) & (body_signed < 0)
    is_shooting_star = (upper_shad > 2 * body) & (lower_shad < 0.5 * body) & (body / (df['high'] - df['low'] + 1e-9) < 0.4) & (body_signed < 0)

    # Engulfing patterns
    prev_body_signed = body_signed.shift(1).fillna(0)
    is_bull_engulf = (prev_body_signed < 0) & (body_signed > 0) & (df['open'] < df['close'].shift(1)) & (df['close'] > df['open'].shift(1))
    is_bear_engulf = (prev_body_signed > 0) & (body_signed < 0) & (df['open'] > df['close'].shift(1)) & (df['close'] < df['open'].shift(1))

    # Rolling support/resistance (simple)
    win = 20
    rolling_high = df['high'].rolling(window=win, min_periods=3).max()
    rolling_low = df['low'].rolling(window=win, min_periods=3).min()

    # Price near support or resistance: within 1%
    near_support = (df['low'] <= rolling_low * 1.01) & (df['low'] >= rolling_low * 0.99)
    near_resistance = (df['high'] >= rolling_high * 0.99) & (df['high'] <= rolling_high * 1.01)

    # Simple double-bottom (W) detection – tiny heuristic: two local lows close in value
    lows = df['low']
    w_pattern = pd.Series(False, index=df.index)
    for i in range(2, len(df) - 2):
        left = lows.iloc[i - 2:i]
        mid = lows.iloc[i]
        right = lows.iloc[i + 1:i + 3]
        if (mid < left.min()) and (mid < right.min()):
            # Check second trough close to first trough (within 2%)
            troughs = [left.min(), mid, right.min()]
            if abs(troughs[0] - troughs[2]) / max(troughs[0], troughs[2], 1e-9) < 0.03:
                w_pattern.iloc[i] = True

    # Combine entry conditions
    buy = (is_hammer | is_bull_engulf | w_pattern | (near_support & (body_signed > 0)))
    sell = (is_shooting_star | is_bear_engulf | (near_resistance & (body_signed < 0)) | is_hanging_man)

    # Build reason strings (prioritise strongest patterns)
    entry_reason = pd.Series('', index=df.index)
    exit_reason = pd.Series('', index=df.index)
    entry_reason[is_hammer] = 'hammer'
    entry_reason[is_bull_engulf] = 'bullish_engulfing'
    entry_reason[w_pattern] = 'W_pattern'
    entry_reason[near_support & (body_signed > 0)] = 'support_bounce'

    exit_reason[is_shooting_star] = 'shooting_star'
    exit_reason[is_bear_engulf] = 'bearish_engulfing'
    exit_reason[near_resistance & (body_signed < 0)] = 'resistance_rejection'
    exit_reason[is_hanging_man] = 'hanging_man'

    # Assign to DataFrame
    df['buy_signal'] = buy.fillna(False)
    df['sell_signal'] = sell.fillna(False)
    df['entry_reason'] = entry_reason.replace('', None)
    df['exit_reason'] = exit_reason.replace('', None)

    # Ensure boolean type
    df['buy_signal'] = df['buy_signal'].astype(bool)
    df['sell_signal'] = df['sell_signal'].astype(bool)

    return df

STRATEGY_MAP = {
    'intraday': {
        "default_timeframes": ["15m"],
        "func": intraday_strategy
    },
    'scalping': {
        "default_timeframes": ["15m"],
        "func": scalping_strategy
    },
    'swing': {
        "default_timeframes": ["2h"],
        "func": swing_strategy
    },
    'short-term': {
        "default_timeframes": ["4h"],
        "func": short_term_strategy
    },
    'long-term': {
        "default_timeframes": ["1d"],
        "func": long_term_strategy
    }
    ,"twin range filter": {
        "func": twin_range_filter_strategy,
        "default_timeframes": ["15m", "1h"]
    }
    , 'ai': {
        "func": ai_strategy,
        "default_timeframes": ["15m", "1h"]
    }
}

# Check if Uptrend is strong using RSI, MACD, Volume, and ATR
def is_uptrend_strong(df: pd.DataFrame) -> bool:
    """
    This function determines if the uptrend is strong based on RSI and MACD indicators.
    A strong uptrend is confirmed if:
    - RSI is greater than 50 (not overbought)
    - MACD line is above the signal line (indicating upward momentum)
    """
    # Ensure there is enough data for the calculations
    if len(df) < 26:
        return False  # Not enough data for MACD

    # Calculate RSI (14-period by default)
    rsi_values = rsi(df['close'], 14)
    
    # Calculate MACD
    macd_line, macd_signal = macd(df['close'])
    
    # Check if the MACD Series is empty
    if macd_line.empty or macd_signal.empty:
        return False

    # Get the last values of RSI and MACD for the latest candle
    rsi_last = rsi_values[-1]
    macd_last = macd_line.iloc[-1]  # Use .iloc[-1] instead of [-1]
    macd_signal_last = macd_signal.iloc[-1]  # Use .iloc[-1] instead of [-1]
    
    # Define conditions for a strong uptrend:
    if rsi_last > 50 and macd_last > macd_signal_last:
        return True
    return False


def is_downtrend_strong(df: pd.DataFrame) -> bool:
    """
    This function determines if the downtrend is strong based on RSI and MACD indicators.
    A strong downtrend is confirmed if:
    - RSI is less than 50 (not oversold)
    - MACD line is below the signal line (indicating downward momentum)
    """
    # Ensure there is enough data for the calculations
    if len(df) < 26:
        return False  # Not enough data for MACD
    
    # Calculate RSI (14-period by default)
    rsi_values = rsi(df['close'], 14)
    
    # Calculate MACD
    macd_line, macd_signal = macd(df['close'])
    
    # Check if the MACD Series is empty
    if macd_line.empty or macd_signal.empty:
        return False

    # Get the last values of RSI and MACD for the latest candle
    rsi_last = rsi_values[-1]
    macd_last = macd_line.iloc[-1]  # Use .iloc[-1] instead of [-1]
    macd_signal_last = macd_signal.iloc[-1]  # Use .iloc[-1] instead of [-1]
    
    # Define conditions for a strong downtrend:
    if rsi_last < 50 and macd_last < macd_signal_last:
        return True
    return False


def run_backtest_dynamic(cfg: BacktestConfig) -> dict:
    # Fetching candles
    candles = fetch_candles(cfg.pair_market, cfg.timeframe, cfg.start_date, cfg.end_date)
    if len(candles) < 60:
        return {"trades": [], "equity": [], "metrics": {}, "daily": {}, "monthly": {}}

    # Convert candles to DataFrame
    df_candles = pd.DataFrame(candles)
    df_candles.rename(columns={'c': 'close', 'h': 'high', 'l': 'low', 'o': 'open', 't': 'time'}, inplace=True)

    # Ensure necessary columns exist for strategies
    if 'close' not in df_candles.columns:
        raise KeyError("'close' column is missing in the DataFrame.")
    if df_candles.empty:
        raise ValueError("The DataFrame is empty. No data to backtest.")

    strategy_name = cfg.strategy_name.lower()
    if strategy_name not in STRATEGY_MAP:
        raise ValueError(f"Strategy '{strategy_name}' is not recognized.")

    # Apply the selected strategy to get signals
    strat_func = STRATEGY_MAP[strategy_name]["func"]
    df_signals = strat_func(df_candles)
    buy_signals = df_signals['buy_signal'].tolist()
    sell_signals = df_signals['sell_signal'].tolist()

    # --- KEY CHANGE: Use a state variable for position type instead of a simple boolean ---
    position_type = None  # Can be None, 'long', or 'short'
    entry_px = 0.0
    qty = 0.0
    entry_ts = None
    trades = []

    fx = usdt_inr_fx()
    usdt_margin = float(cfg.margin_in_inr) / fx if fx > 0 else 0.0
    lev = max(int(cfg.leverage or 1), 1)

    for i in range(1, len(df_candles)):
        px = df_candles['close'][i]
        ts = df_candles['time'][i]

        # --- Case 1: NOT IN A POSITION. Look for an entry. ---
        if position_type is None:
            # Check for a LONG entry signal
            if buy_signals[i]:
                position_type = 'long'
                entry_px = px
                notional = usdt_margin * lev
                qty = notional / entry_px if entry_px > 0 else 0.0
                entry_ts = ts
            # Check for a SHORT entry signal
            elif sell_signals[i]:
                position_type = 'short'
                entry_px = px
                notional = usdt_margin * lev
                qty = notional / entry_px if entry_px > 0 else 0.0
                entry_ts = ts

        # --- Case 2: IN A LONG POSITION. Look for an exit. ---
        elif position_type == 'long':
            if sell_signals[i]:  # Exit a long position on a sell signal
                exit_px = px
                pnl_usdt = (exit_px - entry_px) * qty # PnL for a long trade
                # Pull exit reason from df_signals if present
                exit_reason = None
                try:
                    exit_reason = df_signals.get('exit_reason', pd.Series([None]*len(df_candles))).iloc[i]
                except Exception:
                    exit_reason = None
                trades.append({
                    "side": "long", "entry_ts": entry_ts, "exit_ts": ts,
                    "entry_price": round(entry_px, 6), "exit_price": round(exit_px, 6),
                    "qty": round(qty, 6),
                    "pnl_usdt": round(pnl_usdt, 6),
                    "pnl_inr_value": round(pnl_usdt * fx, 2) if is_finite(pnl_usdt) and is_finite(fx) else None,
                    "pnl_inr": round(pnl_usdt * fx, 2) if is_finite(pnl_usdt) and is_finite(fx) else None,
                    "pnl_inr_str": format_inr_from_usdt(pnl_usdt, fx),
                    "reason": (exit_reason or "strategy_exit")
                })
                position_type = None # Reset state

        # --- Case 3: IN A SHORT POSITION. Look for an exit. ---
        elif position_type == 'short':
            if buy_signals[i]:  # Exit a short position on a buy signal
                exit_px = px
                pnl_usdt = (entry_px - exit_px) * qty # PnL for a short trade (reversed)
                exit_reason = None
                try:
                    exit_reason = df_signals.get('exit_reason', pd.Series([None]*len(df_candles))).iloc[i]
                except Exception:
                    exit_reason = None
                trades.append({
                    "side": "short", "entry_ts": entry_ts, "exit_ts": ts,
                    "entry_price": round(entry_px, 6), "exit_price": round(exit_px, 6),
                    "qty": round(qty, 6),
                    "pnl_usdt": round(pnl_usdt, 6),
                    "pnl_inr_value": round(pnl_usdt * fx, 2) if is_finite(pnl_usdt) and is_finite(fx) else None,
                    "pnl_inr": round(pnl_usdt * fx, 2) if is_finite(pnl_usdt) and is_finite(fx) else None,
                    "pnl_inr_str": format_inr_from_usdt(pnl_usdt, fx),
                    "reason": (exit_reason or "strategy_exit")
                })
                position_type = None # Reset state

    # --- At the end of the backtest, close any remaining open position ---
    if position_type is not None:
        exit_px = df_candles['close'].iloc[-1]
        exit_ts = df_candles['time'].iloc[-1]
        side = ""
        pnl_usdt = 0.0

        if position_type == 'long':
            pnl_usdt = (exit_px - entry_px) * qty
            side = "long"
        
        elif position_type == 'short':
            pnl_usdt = (entry_px - exit_px) * qty
            side = "short"

        # try to use exit_reason from df_signals if available
        final_exit_reason = None
        try:
            final_exit_reason = df_signals.get('exit_reason', pd.Series([None]*len(df_candles))).iloc[-1]
        except Exception:
            final_exit_reason = None
        trades.append({
            "side": side, "entry_ts": entry_ts, "exit_ts": exit_ts,
            "entry_price": round(entry_px, 6), "exit_price": round(exit_px, 6),
            "qty": round(qty, 6),
            "pnl_usdt": round(pnl_usdt, 6),
            "pnl_inr_value": round(pnl_usdt * fx, 2) if is_finite(pnl_usdt) and is_finite(fx) else None,
            "pnl_inr": round(pnl_usdt * fx, 2) if is_finite(pnl_usdt) and is_finite(fx) else None,
            "pnl_inr_str": format_inr_from_usdt(pnl_usdt, fx),
            "reason": (final_exit_reason or "eod") # End of data
        })

    # Generate equity curve and metrics
    equity, daily_map, monthly_map, metrics = equity_and_metrics(trades, fx, start_val_inr=0.0)

    return {
        "trades": trades,
        "equity": equity,
        "daily": daily_map,
        "monthly": monthly_map,
        "metrics": metrics
    }

def equity_and_metrics(trades: list[dict], fx_inr: float, start_val_inr: float = 0.0):
    """Build equity curve, daily pnl, monthly breakdown, drawdown, and detailed metrics."""

    daily_map = {}  # date -> pnl_inr
    for tr in trades:
        entry_date = safe_date(tr.get("entry_ts"))
        exit_date  = safe_date(tr.get("exit_ts"))
        d = exit_date or entry_date
        if not d:
            print("⚠️ Skipping trade with bad timestamps:", tr)
            continue
        daily_map[d] = daily_map.get(d, 0.0) + float(tr["pnl_inr"])

    # Equity curve
    days = sorted(daily_map.keys())
    equity = []
    cum = start_val_inr
    max_peak = start_val_inr
    max_dd = 0.0
    for d in days:
        cum += daily_map[d]
        equity.append({"date": d, "equity": round(cum, 2)})
        max_peak = max(max_peak, cum)
        dd = max_peak - cum
        max_dd = max(max_dd, dd)

    # Trades summary
    wins = sum(1 for tr in trades if tr["pnl_inr"] > 0)
    losses = sum(1 for tr in trades if tr["pnl_inr"] < 0)
    total = len(trades)
    win_rate = (wins / total * 100.0) if total > 0 else 0.0
    gross_profit = sum(tr["pnl_inr"] for tr in trades if tr["pnl_inr"] > 0)
    gross_loss = -sum(tr["pnl_inr"] for tr in trades if tr["pnl_inr"] < 0)
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
    net_profit = gross_profit - gross_loss

    trading_days = len(days)
    profitable_days = sum(1 for v in daily_map.values() if v > 0)
    loss_days = sum(1 for v in daily_map.values() if v < 0)
    avg_daily = (net_profit / trading_days) if trading_days > 0 else 0.0

    # Win/loss streaks
    cur_win_streak = cur_loss_streak = 0
    max_win_streak = max_loss_streak = 0
    for tr in trades:
        pnl = tr["pnl_inr"]
        if pnl > 0:
            cur_win_streak += 1
            cur_loss_streak = 0
            max_win_streak = max(max_win_streak, cur_win_streak)
        elif pnl < 0:
            cur_loss_streak += 1
            cur_win_streak = 0
            max_loss_streak = max(max_loss_streak, cur_loss_streak)

    # Best / worst day
    best_day = {"date": None, "pnl": float("-inf")}
    worst_day = {"date": None, "pnl": float("inf")}
    for d, pnl in daily_map.items():
        if pnl > best_day["pnl"]:
            best_day = {"date": d, "pnl": pnl}
        if pnl < worst_day["pnl"]:
            worst_day = {"date": d, "pnl": pnl}

    # Monthly breakdown → per year with 12 months
    monthly_table = defaultdict(lambda: [0.0] * 12)
    for d, pnl in daily_map.items():
        y, m, _ = d.split("-")
        monthly_table[int(y)][int(m) - 1] += pnl

    metrics = {
        "total_trades": total,
        "win_rate": round(win_rate, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else None,
        "net_profit": round(net_profit, 2),
        "max_drawdown": round(max_dd, 2),
        "trading_days": trading_days,
        "profitable_days": profitable_days,
        "loss_days": loss_days,
        "avg_daily_pnl": round(avg_daily, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "wins": wins,
        "losses": losses,
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "best_day": best_day,
        "worst_day": worst_day,
    }

    return equity, daily_map, dict(monthly_table), metrics


def convert_to_native_types(data):
    """Recursively convert pandas types (int64, float64, Timestamp) to native Python types."""
    if isinstance(data, pd.DataFrame):
        # Apply conversion for all cells in the DataFrame
        return data.applymap(lambda x: 0.0 if pd.isna(x) else (int(x) if isinstance(x, np.int64) else (float(x) if isinstance(x, np.float64) else x)))
    elif isinstance(data, pd.Series):
        # Apply conversion for Series (single column in DataFrame)
        return data.apply(lambda x: 0.0 if pd.isna(x) else (int(x) if isinstance(x, np.int64) else (float(x) if isinstance(x, np.float64) else x)))
    elif isinstance(data, list):
        # Recursively handle lists
        return [convert_to_native_types(item) for item in data]
    elif isinstance(data, dict):
        # Recursively handle dictionaries
        return {k: convert_to_native_types(v) for k, v in data.items()}
    elif isinstance(data, np.int64):
        return int(data)
    elif isinstance(data, np.float64):
        return float(data)
    elif isinstance(data, pd.Timestamp):
        return str(data)  # Convert pandas timestamps to string
    else:
        return data  # Return as is for other types
    
# ------------------ Backtest API ------------------
@app.route("/api/backtest/<int:config_id>", methods=["POST"])
@login_required
def api_backtest(config_id):
    uid = session["user_id"]
    cfg = BacktestConfig.query.filter_by(id=config_id, user_id=uid).first_or_404()

    # Run the backtest
    result = run_backtest_dynamic(cfg)

    # Convert non-serializable data types to native Python types (int, float, etc.)
    result = convert_to_native_types(result)

    # Store the backtest run results in the database
    run = BacktestRun(config_id=cfg.id, user_id=uid, status="completed",
                      finished_at=datetime.now(timezone.utc),
                      trades=len(result["trades"]),
                      win_rate=result["metrics"].get("win_rate", 0.0),
                      pnl_inr=result["metrics"].get("net_profit", 0.0),
                      pnl_usdt=(result["metrics"].get("net_profit", 0.0) / max(usdt_inr_fx(), 1)),
                      metrics_json=json.dumps(result["metrics"]))
    db.session.add(run)
    db.session.commit()

    return jsonify(result)

# ------------------ Admin Dashboard ------------------
@app.route("/admin/dashboard", endpoint="admin_dashboard")
@admin_required
def admin_dashboard():
    return render_template("admin/admin_dashboard.html")


@app.route('/admin/db_control', methods=['GET'])
@admin_required
def admin_db_control():
    """Render the DB control board for admins: list/create/edit/drop views and run queries."""
    return render_template('admin/db_control.html')


@app.route('/admin/db_control/views', methods=['GET'])
@admin_required
def admin_db_control_views():
    """Return JSON list of views (name and SQL) for the current sqlite DB."""
    try:
        rows = db.session.execute(text("SELECT name, sql FROM sqlite_master WHERE type='view' ORDER BY name"))
        out = []
        for r in rows:
            out.append({"name": r[0], "sql": r[1]})
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/admin/db_control/create_view', methods=['POST'])
@admin_required
def admin_db_control_create_view():
    data = request.get_json(silent=True) or request.form
    name = (data.get('view_name') or '').strip()
    sql_body = data.get('view_sql')
    if not name or not sql_body:
        return jsonify({"success": False, "error": "view_name and view_sql required"}), 400
    try:
        # Use DROP then CREATE to replace existing view safely
        db.session.execute(text(f'DROP VIEW IF EXISTS "{name}"'))
        db.session.execute(text(f'CREATE VIEW "{name}" AS {sql_body}'))
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin/db_control/drop_view', methods=['POST'])
@admin_required
def admin_db_control_drop_view():
    data = request.get_json(silent=True) or request.form
    name = (data.get('view_name') or '').strip()
    if not name:
        return jsonify({"success": False, "error": "view_name required"}), 400
    try:
        db.session.execute(text(f'DROP VIEW IF EXISTS "{name}"'))
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin/db_control/run_query', methods=['POST'])
@admin_required
def admin_db_control_run_query():
    data = request.get_json(silent=True) or request.form
    sql = (data.get('sql') or '').strip()
    page = int(data.get('page') or 1)
    per_page = int(data.get('per_page') or 200)
    export_csv = bool(data.get('export_csv') in (True, 'true', '1', 1))
    if not sql:
        return jsonify({"error": "sql required"}), 400
    # allow only safe read queries by default
    first = sql.split()[0].upper() if sql.split() else ''
    # support advanced DDL only if admin has enabled advanced mode in session
    allowed_read = ('SELECT', 'PRAGMA')
    # allow DDL and DML in advanced mode (admin explicitly enabled)
    allowed_advanced = ('CREATE', 'ALTER', 'DROP', 'CREATE INDEX', 'UPDATE', 'INSERT', 'DELETE')
    adv_enabled = session.get('db_control_advanced', False)
    if first not in allowed_read and not (adv_enabled and first in allowed_advanced):
        return jsonify({"error": "Only SELECT and PRAGMA allowed unless advanced mode is enabled"}), 403
    try:
        # If it's a read query, paginate
        if first in allowed_read:
            # If export_csv requested, return the full result set (with a server-side cap)
            if export_csv:
                # safety cap rows
                MAX_EXPORT_ROWS = 100000
                try:
                    res_all = db.session.execute(text(sql))
                    cols = list(res_all.keys())
                    rows_all = []
                    ctr = 0
                    for r in res_all:
                        rows_all.append(list(r))
                        ctr += 1
                        if ctr >= MAX_EXPORT_ROWS:
                            break
                    import io, csv
                    si = io.StringIO()
                    cw = csv.writer(si)
                    cw.writerow(cols)
                    for r in rows_all:
                        cw.writerow(r)
                    return jsonify({"csv": si.getvalue(), "truncated": ctr >= MAX_EXPORT_ROWS})
                except Exception as e:
                    return jsonify({"error": str(e)}), 500
            # For normal paging, wrap with limit/offset (SQLite supports LIMIT/OFFSET)
            offset = (max(1, page) - 1) * max(1, per_page)
            paged_sql = f"{sql} LIMIT {per_page} OFFSET {offset}"
            res = db.session.execute(text(paged_sql))
            cols = list(res.keys())
            rows = [list(r) for r in res.fetchall()]
            # quick count (best effort) for UI pagination
            try:
                count_sql = f"SELECT COUNT(1) FROM ({sql}) as _cnt"
                cnt_res = db.session.execute(text(count_sql)).scalar()
            except Exception:
                cnt_res = None
            return jsonify({"columns": cols, "rows": rows, "count": cnt_res, "page": page, "per_page": per_page})
        else:
            # non-read advanced statement
            res = db.session.execute(text(sql))
            db.session.commit()
            return jsonify({"success": True, "message": "Statement executed"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/admin/db_control/enable_advanced', methods=['POST'])
@admin_required
def admin_db_control_enable_advanced():
    # Toggle advanced mode in session; requires explicit confirmation in UI
    data = request.get_json(silent=True) or request.form
    enable = data.get('enable') in (True, 'true', '1', 1)
    session['db_control_advanced'] = bool(enable)
    return jsonify({"success": True, "enabled": bool(enable)})

@app.route("/algo_trading", endpoint="algo_trading")
@login_required
def algo_trading():
    user = db.session.get(User, session["user_id"])
    creds = Credentials.query.filter_by(user_id=user.id).first()
    # if not creds:
    #     return jsonify({"error": "No API credentials found"})
    
    # return render_template("algo_trading.html", user=user, creds=creds)
    
    api_credentials_updated = bool(creds)  # True if creds exists, False if None
    
    return render_template("algo_trading.html", user=user, creds=creds, api_credentials_updated=api_credentials_updated)

# ------------------ Delete Strategy ------------------
@app.route("/admin/strategies/<int:id>/delete", methods=["POST"])
@admin_required
def delete_strategy(id):
    s = Strategy.query.get_or_404(id)
    db.session.delete(s)
    db.session.commit()
    flash("Strategy deleted", "warning")
    return redirect(url_for("manage_strategies"))

@app.route("/admin/strategies/<int:id>/edit", methods=["POST"])
@admin_required
def edit_strategy(id):
    s = Strategy.query.get_or_404(id)

    # Pull data from the form
    s.name = request.form.get("name")
    s.description = request.form.get("description")
    s.video_url = request.form.get("video_url")
    s.signals = request.form.get("signals")
    s.difficulty = request.form.get("difficulty")
    s.timeframe = request.form.get("timeframe")
    s.gain = request.form.get("gain")
    s.users = request.form.get("users")
    s.is_active = True if request.form.get("is_active") else False

    db.session.commit()
    flash(f"Strategy '{s.name}' updated successfully!", "success")
    return redirect(url_for("manage_strategies"))

# ------------------ User Management ------------------
@app.route("/admin/users", endpoint="user_management")
@admin_required
def user_management():
    users = User.query.all()
    roles = Role.query.all()
    return render_template("admin/user_management.html", users=users, roles=roles)


@app.route("/admin/users/<int:id>/delete", methods=["POST"])
@admin_required
def delete_user(id):
    user = User.query.get_or_404(id)

    # prevent deleting yourself
    if user.id == session.get("user_id"):
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("user_management"))

    db.session.delete(user)
    db.session.commit()
    flash("User deleted successfully.", "warning")
    return redirect(url_for("user_management"))


@app.route("/admin/users/<int:id>/set_role/<role_name>", methods=["POST"])
@admin_required
def set_user_role(id, role_name):
    user = User.query.get_or_404(id)
    role = Role.query.filter_by(name=role_name).first()

    if not role:
        flash("Invalid role.", "danger")
        return redirect(url_for("user_management"))

    user.role_id = role.id
    db.session.commit()
    flash(f"User role updated to {role_name}.", "success")
    return redirect(url_for("user_management"))

# ------------------ Positions & History Routes ------------------
@app.route("/get_positions")
@login_required
def get_positions():

    uid = session["user_id"]
    creds = Credentials.query.filter_by(user_id=uid).first()
    if not creds:
        return jsonify({"error": "No API credentials found"})

    # --- Robust FX: prefer API-based USD→INR, never let NaN pass through
    fx_inr = usdt_inr_fx()
    if not is_finite(fx_inr) or fx_inr <= 0:
        fx_inr = 89.0  # hard fallback

    closed_rows = []
    open_positions = []

    try:
        # Fast CoinDCX API fetch and normalization
        # Test hook: if the user's creds are blank and TEST_ACTIONS=1, use synthetic orders
        if (not creds.api_key or str(creds.api_key).strip() == '') and os.environ.get('TEST_ACTIONS', '0') == '1':
            # Build a tiny synthetic normalized-orders list so derive_from_trades produces an OPEN position
            now_ms = _now_ms()
            all_orders_norm = [
                {
                    "id": "t1",
                    "pair": "BINANCE:ETHUSDT",
                    "side": "buy",
                    "status": "filled",
                    "qty_num": 1.0,
                    "price_num": 1000.0,
                    "created_at_raw": now_ms - 20000,
                    "updated_at_raw": now_ms - 20000,
                },
                {
                    "id": "t2",
                    "pair": "BINANCE:ETHUSDT",
                    "side": "buy",
                    "status": "filled",
                    "qty_num": 1.0,
                    "price_num": 1100.0,
                    "created_at_raw": now_ms - 10000,
                    "updated_at_raw": now_ms - 10000,
                }
            ]
            open_positions, closed_rows = derive_from_trades(all_orders_norm, fx_inr)
        else:
            all_orders_raw = fetch_all_orders(creds)
            all_orders_norm = [normalize_order(o) for o in all_orders_raw]
            open_positions, closed_rows = derive_from_trades(all_orders_norm, fx_inr)
    except Exception as e:
        print("error derive_from_trades:", e)

    # Augment open positions with LTP and robust P&L calculation
    try:
        for r in open_positions:
            try:
                pair = (r.get('pair') or '').strip()
                short = pair.split(':')[-1] if ':' in pair else pair
                if short.startswith('B-'):
                    short = short[2:]
                short = short.replace('_', '').replace('/', '').upper()
                ltp = None
                if short:
                    ltp = None
                    # Try cache first
                    if short in LTP_CACHE:
                        try:
                            ltp = float(LTP_CACHE.get(short))
                        except Exception:
                            ltp = None
                    # Fallback to API
                    if ltp is None:
                        try:
                            ltp = fetch_ltp_from_api(short)
                        except Exception:
                            ltp = None
                r['ltp'] = ltp
                # Calculate P&L if possible
                try:
                    entry_px = float(r.get('entry_px', 0))
                    qty = float(r.get('qty', 0))
                    side = str(r.get('side', 'BUY')).upper()
                    # Accept various side synonyms returned by different normalization
                    if side in ('LONG', 'LONG/BUY'):
                        side_norm = 'BUY'
                    elif side in ('SHORT', 'SHORT/SELL'):
                        side_norm = 'SELL'
                    else:
                        side_norm = side

                    if ltp is not None and entry_px > 0 and qty > 0:
                        if side_norm == 'BUY' or side_norm == 'LONG':
                            r['pnl_open_inr'] = round((ltp - entry_px) * qty, 2)
                        elif side_norm == 'SELL' or side_norm == 'SHORT':
                            r['pnl_open_inr'] = round((entry_px - ltp) * qty, 2)
                        else:
                            r['pnl_open_inr'] = None
                    else:
                        r['pnl_open_inr'] = None
                except Exception:
                    r['pnl_open_inr'] = None
                # ensure strategy field exists for UI
                if 'strategy' not in r:
                    r['strategy'] = r.get('strategy', '-')
            except Exception:
                r['ltp'] = None
                r['pnl_open_inr'] = None
    except Exception:
        pass

    return jsonify({"open": open_positions, "closed": closed_rows})


@app.route('/paper_positions')
@login_required
def paper_positions():
    """Return simulated open positions for paper trading for the current user."""
    uid = session['user_id']

    # Ensure the DB has the paper_order_id column and backfill missing values
    try:
        info = db.session.execute(text("PRAGMA table_info('paper_trades')")).fetchall()
        cols = [r[1] for r in info]
        if 'paper_order_id' not in cols:
            try:
                db.session.execute(text("ALTER TABLE paper_trades ADD COLUMN paper_order_id TEXT"))
                db.session.commit()
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    pass
        # backfill any rows missing paper_order_id
        missing = db.session.query(PaperTrade).filter((PaperTrade.paper_order_id == None) | (PaperTrade.paper_order_id == '')).all()
        import uuid
        for mt in missing:
            try:
                mt.paper_order_id = f"PAPER-{uuid.uuid4().hex}"
            except Exception:
                continue
        if missing:
            try:
                db.session.commit()
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    pass
    except Exception:
        # best-effort: ignore DB introspection failures
        pass

    rows = PaperTrade.query.filter_by(user_id=uid, status='OPEN').order_by(PaperTrade.entry_time.desc()).all()
    out = []
    for r in rows:
        try:
            short = (r.tv_symbol or r.symbol or '').split(':')[-1].replace('.P','').replace('_','').upper()
            ltp = None
            if short:
                if short in LTP_CACHE:
                    try:
                        ltp = float(LTP_CACHE.get(short))
                    except Exception:
                        ltp = None
                if ltp is None:
                    try:
                        ltp = fetch_ltp_from_api(short)
                    except Exception:
                        ltp = None
            entry_px = float(r.entry_price or 0)
            qty = float(r.qty or 0)
            side = str(r.side or 'BUY').upper()
            pnl_open_inr = None
            pnl_usdt = None
            pnl_inr_value = None
            if ltp is not None and entry_px > 0 and qty > 0:
                if side == 'BUY':
                    pnl_usdt = round((ltp - entry_px) * qty, 6)
                elif side == 'SELL':
                    pnl_usdt = round((entry_px - ltp) * qty, 6)
                if pnl_usdt is not None:
                    fx = usdt_inr_fx()
                    pnl_inr_value = round(pnl_usdt * fx, 2) if is_finite(pnl_usdt) and is_finite(fx) else None
                    pnl_open_inr = pnl_inr_value
            out.append({
                'id': r.id,
                'order_id': r.paper_order_id,
                'pair': r.symbol,
                'tv_symbol': (r.tv_symbol or None),
                'side': r.side,
                'entry_at': r.entry_time and r.entry_time.isoformat(),
                'entry_px': r.entry_price,
                'qty': r.qty,
                'pnl_usdt': pnl_usdt,
                'pnl_open_inr_value': pnl_inr_value,
                'pnl_open_inr': pnl_open_inr,
                'margin': r.margin,
                'leverage': r.leverage,
                'locked_amount': r.locked_amount,
                'lev': r.leverage or 1,
                'mark_px': r.entry_price,
                'updated_at': (r.entry_time and r.entry_time.isoformat()),
                'ltp': ltp,
                'strategy': r.strategy or '-'
            })
        except Exception:
            out.append({
                'id': r.id,
                'order_id': r.paper_order_id,
                'pair': r.symbol,
                'tv_symbol': (r.tv_symbol or None),
                'side': r.side,
                'entry_at': r.entry_time and r.entry_time.isoformat(),
                'entry_px': r.entry_price,
                'qty': r.qty,
                'pnl_open_inr': None,
                'margin': r.margin,
                'leverage': r.leverage,
                'locked_amount': r.locked_amount,
                'lev': r.leverage or 1,
                'mark_px': r.entry_price,
                'updated_at': (r.entry_time and r.entry_time.isoformat()),
                'ltp': None,
                'strategy': r.strategy or '-'
            })
    return jsonify({'open': out})


@app.route('/paper_history')
@login_required
def paper_history():
    """Return closed paper trades for the current user, latest first and include released PnL."""
    uid = session['user_id']
    rows = PaperTrade.query.filter_by(user_id=uid, status='CLOSED').order_by(PaperTrade.exit_time.desc()).all()
    out = []
    for r in rows:
        try:
            out.append({
                'id': r.id,
                'order_id': r.paper_order_id,
                'pair': r.symbol,
                'tv_symbol': (r.tv_symbol or None),
                'side': r.side,
                'entry_at': r.entry_time and r.entry_time.isoformat(),
                'entry_px': r.entry_price,
                'exit_at': r.exit_time and r.exit_time.isoformat(),
                'exit_px': r.exit_price,
                'qty': r.qty,
                'strategy': r.strategy or '-',
                'margin': r.margin,
                'leverage': r.leverage,
                'locked_amount': r.locked_amount,
                'released_pnl': r.pnl_inr
            })
        except Exception:
            out.append({
                'id': r.id,
                'order_id': r.paper_order_id,
                'pair': r.symbol,
                'tv_symbol': (r.tv_symbol or None),
                'side': r.side,
                'entry_at': r.entry_time and r.entry_time.isoformat(),
                'entry_px': r.entry_price,
                'exit_at': None,
                'exit_px': None,
                'qty': r.qty,
                'strategy': r.strategy or '-',
                'margin': r.margin,
                'leverage': r.leverage,
                'locked_amount': r.locked_amount,
                'released_pnl': None
            })
    return jsonify({'closed': out})

@app.route("/trade_history")
# @login_required

def trade_history():
    user_id = session["user_id"]
    cache_key = f"trade_history:{user_id}"
    cache_ttl = 60  # seconds
    closed = []
    total = wins = losses = acc = net_pnl = 0
    creds = Credentials.query.filter_by(user_id=user_id).first()
    if not creds:
        flash("No credentials found", "danger")
        return redirect(url_for("dashboard"))

    # Try to serve from Redis cache first
    cached = None
    if _redis:
        try:
            cached = _redis.get(cache_key)
            if cached:
                cached = json.loads(cached)
        except Exception:
            cached = None

    if cached:
        closed = cached.get('closed', [])
        total = cached.get('total', 0)
        wins = cached.get('wins', 0)
        losses = cached.get('losses', 0)
        acc = cached.get('acc', 0)
        net_pnl = cached.get('net_pnl', 0)
    else:
        try:
            fx_inr = usdt_inr_fx()
            raw_orders = fetch_all_orders(creds)
            norm = [normalize_order(o) for o in raw_orders]
            _, closed = derive_from_trades(norm, fx_inr)

            total = len(closed)
            wins = sum(1 for t in closed if (_pnl_num_from_row(t) is not None) and _pnl_num_from_row(t) >= 0)
            losses = sum(1 for t in closed if (_pnl_num_from_row(t) is not None) and _pnl_num_from_row(t) < 0)
            acc = round((wins / total * 100), 1) if total > 0 else 0
            net_pnl = sum((_pnl_num_from_row(t) or 0.0) for t in closed)

            # Cache the result
            if _redis:
                try:
                    _redis.setex(cache_key, cache_ttl, json.dumps({
                        'closed': closed,
                        'total': total,
                        'wins': wins,
                        'losses': losses,
                        'acc': acc,
                        'net_pnl': net_pnl
                    }))
                except Exception:
                    pass
        except Exception as e:
            print("trade_history error:", e)

    # Always update cache in the background for next time
    def update_trade_history_cache_async(uid, creds):
        try:
            fx_inr = usdt_inr_fx()
            raw_orders = fetch_all_orders(creds)
            norm = [normalize_order(o) for o in raw_orders]
            _, closed = derive_from_trades(norm, fx_inr)
            total = len(closed)
            wins = sum(1 for t in closed if (_pnl_num_from_row(t) is not None) and _pnl_num_from_row(t) >= 0)
            losses = sum(1 for t in closed if (_pnl_num_from_row(t) is not None) and _pnl_num_from_row(t) < 0)
            acc = round((wins / total * 100), 1) if total > 0 else 0
            net_pnl = sum((_pnl_num_from_row(t) or 0.0) for t in closed)
            if _redis:
                _redis.setex(f"trade_history:{uid}", cache_ttl, json.dumps({
                    'closed': closed,
                    'total': total,
                    'wins': wins,
                    'losses': losses,
                    'acc': acc,
                    'net_pnl': net_pnl
                }))
        except Exception:
            pass
    if _redis:
        import threading
        threading.Thread(target=update_trade_history_cache_async, args=(user_id, creds), daemon=True).start()

    user = db.session.get(User, user_id)

    # Determine currency label for UI: prefer user.currency, then creds.currency, then inspect sample pnl
    currency_label = None
    try:
        if user and getattr(user, 'currency', None):
            c = str(user.currency or '').upper()
            if c in ('USDT', 'USD'):
                currency_label = '$'
            else:
                currency_label = c
        elif creds and getattr(creds, 'currency', None):
            c = str(creds.currency or '').upper()
            if c in ('USDT', 'USD'):
                currency_label = '$'
            else:
                currency_label = c
    except Exception:
        currency_label = None

    if not currency_label:
        # fallback: inspect first trade numeric pnl or formatted string
        if closed:
            first = closed[0]
            # prefer numeric presence
            if first.get('pnl_inr_value') is not None or isinstance(first.get('pnl_inr'), (int, float)):
                currency_label = 'INR'
            else:
                sample = str(first.get('pnl_inr_str','') or '')
                if sample.startswith('$'):
                    currency_label = '$'
                elif sample.startswith('₹') or 'INR' in sample:
                    currency_label = 'INR'
                else:
                    currency_label = 'INR'
        else:
            currency_label = 'INR'

    return render_template(
        "trade_history.html",
        trades=closed,
        total=total,
        wins=wins,
        losses=losses,
        acc=acc,
        net_pnl=net_pnl,
        user=user,
        creds=creds,
        currency_label=currency_label
    )


def _compute_trade_history_for_user(creds: Credentials) -> dict:
    """Compute trade history from API and return structured dict.
    Returns: { closed: [...], total, wins, losses, acc, net_pnl }
    """
    fx_inr = usdt_inr_fx()
    all_orders_raw = fetch_all_orders(creds)
    all_orders_norm = [normalize_order(o) for o in all_orders_raw]
    _, closed = derive_from_trades(all_orders_norm, fx_inr)

    total = len(closed)
    wins = sum(1 for t in closed if (_pnl_num_from_row(t) is not None) and _pnl_num_from_row(t) >= 0)
    losses = sum(1 for t in closed if (_pnl_num_from_row(t) is not None) and _pnl_num_from_row(t) < 0)
    acc = round((wins / total * 100), 1) if total > 0 else 0
    net_pnl = sum((_pnl_num_from_row(t) or 0.0) for t in closed)

    return {
        'closed': closed,
        'total': total,
        'wins': wins,
        'losses': losses,
        'acc': acc,
        'net_pnl': net_pnl
    }


@app.route('/trade_history/export')
@login_required
def export_trade_history():
    uid = session['user_id']
    creds = Credentials.query.filter_by(user_id=uid).first()
    if not creds:
        return redirect(url_for('trade_history'))

    # Prefer cached value if present
    cache_key = f"trade_history:{uid}"
    cached = None
    if _redis:
        try:
            val = _redis.get(cache_key)
            if val:
                cached = json.loads(val)
        except Exception:
            cached = None

    if cached:
        data = cached
    else:
        data = _compute_trade_history_for_user(creds)
        if _redis:
            try:
                _redis.setex(cache_key, 60, json.dumps(data))
            except Exception:
                pass

    # Build CSV
    import io
    si = io.StringIO()

    # Determine currency label for header. Prefer broker / balance API, fallback to inspecting trade pnl strings.
    currency_label = "INR"
    try:
        bal = get_balance_from_api(creds.api_key, creds.secret_key)
        if isinstance(bal, dict) and bal.get("currency"):
            c = str(bal.get("currency") or "").upper()
            if c in ("USDT", "USD"):
                currency_label = "$"
            elif c == "INR":
                currency_label = "INR"
            else:
                # Use raw currency code as fallback (e.g., 'USDT')
                currency_label = c
    except Exception:
        pass

    # If still unknown, inspect first trade's pnl string for hints
    if not currency_label or currency_label == "":
        closed = data.get('closed', [])
        if closed:
            sample = str(closed[0].get('pnl_inr', '') or '')
            if sample.startswith('$'):
                currency_label = '$'
            elif sample.startswith('₹') or 'INR' in sample:
                currency_label = 'INR'

    cols = ["id", "pair", "side", "qty", "entry_px", "exit_px", "lev", f"pnl ({currency_label})", "entry_at", "exit_at"]
    si.write(','.join(cols) + '\n')

    def _clean_pnl(row):
        # Prefer numeric value if present
        num = _pnl_num_from_row(row)
        if num is not None:
            if float(num).is_integer():
                return str(int(num))
            return str(float(num))
        # fallback: sanitize string
        s = str(row or '')
        for ch in ['$', '₹', 'INR', ',']:
            s = s.replace(ch, '')
        return s.strip()

    for t in data.get('closed', []):
        pnl_clean = _clean_pnl(t)
        row = [
            str(t.get('id','')),
            str(t.get('pair','')),
            str(t.get('side','')),
            str(t.get('qty','')),
            str(t.get('entry_px','')),
            str(t.get('exit_px','')),
            str(t.get('lev','')),
            '"' + pnl_clean + '"',
            str(t.get('entry_at','')),
            str(t.get('exit_at',''))
        ]
        si.write(','.join(row) + '\n')

    output = si.getvalue()
    from flask import Response
    resp = Response(output, mimetype='text/csv')
    resp.headers['Content-Disposition'] = 'attachment; filename=trade_history.csv'
    return resp


@app.route('/trade_history/refresh')
@login_required
def refresh_trade_history():
    """Fetch latest trades from API, update cache, and return JSON payload for UI update."""
    uid = session['user_id']
    creds = Credentials.query.filter_by(user_id=uid).first()
    if not creds:
        return jsonify({'error': 'no_credentials'}), 400

    data = _compute_trade_history_for_user(creds)
    # update cache
    if _redis:
        try:
            _redis.setex(f"trade_history:{uid}", 60, json.dumps(data))
        except Exception:
            pass

    return jsonify(data)

# ------------------ Algo Strategy Routes ------------------

@app.route("/algo_setup", methods=["GET"], endpoint="algo_setup")
@login_required
def algoStrategy_page():
    uid = session["user_id"]
    user = db.session.get(User, session["user_id"])
    creds = Credentials.query.filter_by(user_id=user.id).first()

    # Pagination params
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 10))
    except Exception:
        page, per_page = 1, 10
    offset = (page - 1) * per_page

    # Build choices for the symbol select (fallback in case JS fails)
    choices = []
    try:
        actives = get_active_instruments_tv()  # returns [{label, tv}]
        choices = [(x["tv"], x["label"]) for x in actives][:300]
    except Exception:
        pass

    form = StrategyPopupForm()
    form.symbol_tv.choices = choices

    # Paginated query
    total_count = db.session.query(UserStrategySetup).filter(UserStrategySetup.user_id == uid).count()
    user_strategies = (
        db.session.query(UserStrategySetup, Strategy)
        .join(Strategy)
        .filter(UserStrategySetup.user_id == uid)
        .order_by(UserStrategySetup.id.desc())
        .offset(offset)
        .limit(per_page)
        .all()
    )

    all_strategies = Strategy.query.all()

    # Use cached signals if available, otherwise show '-'.
    processed_strategies = []
    for user_strategy, strategy in user_strategies:
        # Normalize symbol into a short alphanumeric label like ETHUSDT
        try:
            raw = (user_strategy.symbol or '')
            short = raw.split(':')[-1]
            # remove market prefix if present (e.g. B-)
            if short.startswith('B-'):
                short = short[2:]
            # remove underscores, dots and other non-alphanumeric characters
            cleaned_symbol = ''.join([c for c in short if c.isalnum()]).upper()
            if not cleaned_symbol:
                cleaned_symbol = (short or '').upper()
        except Exception:
            cleaned_symbol = (user_strategy.symbol or '').split(':')[-1].replace('_','').upper()
        # Try to get cached signal
        sig_rec = SIGNAL_CACHE.get(user_strategy.id)
        signal = sig_rec['signal'] if sig_rec else '-'
        processed_strategies.append((user_strategy, strategy, cleaned_symbol, signal))

    total_pages = (total_count + per_page - 1) // per_page

    return render_template(
        "algo_setup.html",
        form=form,
        strategies=processed_strategies,
        all_strategies=all_strategies,
        user=user,
        creds=creds,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        total_count=total_count
    )


@app.route('/algo_setup/signals', methods=['GET','POST'])
@login_required
def algo_setup_signals():
    """Fast endpoint to return signals for requested user strategy ids or symbols.
    Request options:
      - GET ?ids=1,2,3  -> returns signals for those config ids
      - POST JSON { ids: [1,2], symbols: ['BTCUSDT'] }
    Response: { signals: { config_id: signal, symbol: signal, ... }, optional 'logs' }
    """
    out = {'signals': {}}
    req_ids = []
    req_symbols = []
    logs = []
    try:
        if request.method == 'GET':
            q = request.args.get('ids')
            if q:
                req_ids = [int(x) for x in q.split(',') if x.strip().isdigit()]
        else:
            js = request.get_json(silent=True) or {}
            req_ids = [int(x) for x in (js.get('ids') or []) if isinstance(x, (int, str)) and str(x).isdigit()]
            req_symbols = [s.upper() for s in (js.get('symbols') or []) if s]

        # Serve from Redis or in-memory cache when fresh
        for cid in req_ids:
            data = None
            if _redis:
                try:
                    data = redis_get_signal(int(cid))
                except Exception:
                    data = None
            if not data:
                data = SIGNAL_CACHE.get(int(cid))
            if data and (int(time.time() * 1000) - int(data.get('updated_at', 0)) <= SIGNAL_TTL * 1000):
                out['signals'][str(cid)] = data

        # For symbol lookups, fallback to in-memory scan
        for sym in req_symbols:
            for cid, v in list(SIGNAL_CACHE.items()):
                if (v.get('symbol') or '').upper().endswith(sym) or (v.get('symbol') or '').upper() == sym:
                    out['signals'][sym] = v
                    break

        # Compute any missing ids synchronously and, for paper setups, process paper trades immediately
        missing_ids = [i for i in req_ids if str(i) not in out['signals']]
        if missing_ids:
            rows = db.session.query(UserStrategySetup, Strategy).join(Strategy).filter(UserStrategySetup.id.in_(missing_ids)).all()
            for us, strat in rows:
                try:
                    sig = _compute_signal_for_user_strategy(us, strat)
                except Exception:
                    sig = '-'
                rec = {'signal': sig, 'updated_at': int(time.time() * 1000), 'symbol': us.symbol}
                out['signals'][str(us.id)] = rec
                SIGNAL_CACHE[us.id] = rec

                if getattr(us, 'is_paper', False) and sig in ('BUY', 'SELL'):
                    # quick price fetch
                    try:
                        short = (us.symbol.split(':')[-1] if us.symbol else '').replace('_', '')
                        cur_px = fetch_ltp_from_api(short)
                    except Exception:
                        cur_px = None
                    try:
                        process_paper_signal(us, sig, cur_px, strat.name if strat else None, trend_confirmed=True)
                        db.session.commit()
                        logs.append(f'processed_sync:{us.id}:sig={sig}')
                    except Exception as e:
                        try:
                            db.session.rollback()
                        except Exception:
                            pass
                        logs.append(f'process_error_sync:{us.id}:{e}')

        # Test-only processing: if TEST_ACTIONS=1 and caller requests processing, run processing for requested ids
        js_body = request.get_json(silent=True) or {}
        if js_body.get('process') and os.environ.get('TEST_ACTIONS', '0') == '1':
            for cid in req_ids:
                us = db.session.get(UserStrategySetup, cid)
                if not us:
                    logs.append(f'config_not_found:{cid}')
                    continue
                strat_obj = db.session.get(Strategy, us.strategy_id) if us.strategy_id else None
                # attempt to fetch a current price
                cur_px = None
                try:
                    pair_market = tv_to_pair_market(us.symbol)
                    tf = (us.timeframe or '15m').lower()
                    end_dt = datetime.now(timezone.utc)
                    start_dt = end_dt - timedelta(days=7)
                    candles = fetch_candles(pair_market, tf, start_dt, end_dt)
                    cur_px = float(candles[-1]['c']) if candles else None
                except Exception as e:
                    logs.append(f'candles_error:{cid}:{e}')

                sig = (out['signals'].get(str(cid)) or '-')
                try:
                    before = PaperTrade.query.filter_by(user_id=us.user_id, config_id=us.id, status='OPEN').count()
                except Exception:
                    before = 0
                try:
                    process_paper_signal(us, sig, cur_px, strat_obj.name if strat_obj else None, trend_confirmed=True)
                    db.session.commit()
                except Exception as e:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                    logs.append(f'process_error:{cid}:{e}')
                try:
                    after = PaperTrade.query.filter_by(user_id=us.user_id, config_id=us.id, status='OPEN').count()
                except Exception:
                    after = 0
                logs.append(f'processed:{cid}:before={before}:after={after}:sig={sig}')

        # Normalize output and return
        normalized = {'signals': {}}
        for k, v in out['signals'].items():
            if not v:
                continue
            normalized['signals'][k] = v.get('signal', '-')
        if logs:
            return jsonify({'signals': normalized['signals'], 'logs': logs})
        return jsonify(normalized)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/signals/stream')
@login_required
def signals_stream():
    """Server-Sent Events stream that forwards Redis pubsub 'signals:updates' messages.
    Browsers can connect via EventSource to receive instant updates.
    """
    if not _redis:
        return "Redis not configured", 503

    def event_stream():
        pub = _redis.pubsub(ignore_subscribe_messages=True)
        try:
            pub.subscribe('signals:updates')
            for message in pub.listen():
                if message is None: continue
                data = message.get('data')
                if isinstance(data, bytes):
                    try:
                        data = data.decode('utf-8')
                    except Exception:
                        pass
                # send as SSE event
                try:
                    yield f"data: {data}\n\n"
                except GeneratorExit:
                    break
        finally:
            try: pub.close()
            except Exception: pass

    return app.response_class(event_stream(), mimetype='text/event-stream')


@app.route("/add_algo_strategy", methods=["POST"])
def add_algo_strategy():
    uid = session["user_id"]
    
    # Get form data
    strategy_name = request.form["strategy_name"]
    symbol_tv = request.form["symbol_tv"]
    leverage = request.form["leverage"]
    amount = request.form["amount"]
    timeframe = request.form["timeframe"]  # Get timeframe from the form
    # is_paper may be sent as hidden input 'is_paper' (0/1) or checkbox; default to 0
    try:
        is_paper_val = request.form.get('is_paper', '0')
        is_paper = True if str(is_paper_val) in ('1', 'true', 'True', 'on') else False
    except Exception:
        is_paper = False

    # Find the strategy object by name
    strategy = Strategy.query.filter_by(name=strategy_name).first()

    if strategy:
        # Add new strategy to UserStrategySetup
        new_strategy = UserStrategySetup(
            user_id=uid,
            strategy_id=strategy.id,
            symbol=symbol_tv,
            leverage=leverage,
            margin=amount,
            timeframe=timeframe,  # Save the timeframe
            is_active=True,  # You can change this based on your requirements
            is_paper=is_paper
        )

        db.session.add(new_strategy)
        db.session.commit()

        flash("Strategy created successfully.", "success")
    else:
        flash("Strategy not found.", "danger")
    
    # Correct redirection to the algo_setup route
    return redirect(url_for("algo_setup"))  # This should work

@app.route("/algo_setup/<int:config_id>/edit", methods=["POST"], endpoint="edit_algo_strategy")
@login_required
def edit_algo_strategy(config_id):
    uid = session["user_id"]
    strategy = UserStrategySetup.query.filter_by(id=config_id, user_id=uid).first_or_404()

    # Get form data for updating
    strategy_name = request.form.get("strategy_name")
    symbol_tv = request.form.get("symbol_tv", strategy.symbol)
    leverage = int(request.form.get("leverage", strategy.leverage))
    amount = float(request.form.get("amount", strategy.margin))
    timeframe = request.form.get("timeframe", strategy.timeframe)

    # Get strategy_id and find the corresponding strategy
    updated_strategy = Strategy.query.filter_by(name=strategy_name).first()

    if updated_strategy:
        strategy.strategy_id = updated_strategy.id  # Update the strategy_id
    else:
        flash("Strategy not found.", "danger")
        return redirect(url_for("algo_setup"))

    # Update the other fields
    strategy.symbol = symbol_tv
    strategy.leverage = leverage
    strategy.margin = amount
    strategy.timeframe = timeframe
    # Update is_paper flag if provided in the form
    try:
        is_paper_val = request.form.get('is_paper', None)
        if is_paper_val is not None:
            strategy.is_paper = True if str(is_paper_val) in ('1', 'true', 'True', 'on') else False
    except Exception:
        pass

    db.session.commit()
    flash("Strategy updated successfully.", "success")
    return redirect(url_for("algo_setup"))  # Make sure the URL is correct


@app.route("/algo_setup/<int:config_id>/delete", methods=["POST"], endpoint="delete_algo_strategy")
def delete_algo_strategy(config_id):
    uid = session["user_id"]
    strategy = UserStrategySetup.query.filter_by(id=config_id, user_id=uid).first_or_404()
    db.session.delete(strategy)
    db.session.commit()
    flash("Strategy deleted successfully.", "warning")
    return redirect(url_for("algo_setup"))


@app.route("/algo_setup/<int:config_id>/run", methods=["POST"], endpoint="run_algo")
def run_algo(config_id):
    uid = session["user_id"]
    cfg = BacktestConfig.query.filter_by(id=config_id, user_id=uid).first_or_404()

    db.session.commit()


@app.route('/algo_setup/<int:config_id>/start', methods=['POST'])
@login_required
def start_user_strategy(config_id):
    uid = session['user_id']
    strat = UserStrategySetup.query.filter_by(id=config_id, user_id=uid).first_or_404()
    strat.is_active = True
    db.session.commit()
    # spawn a background thread to perform any expensive follow-up (recompute signal, publish to redis)
    def process_user_strategy_start(cid):
        """Helper to compute signal for a started user-strategy, update caches and
        immediately process paper trades if the setup is paper-mode. Separated
        so tests can call it directly."""
        try:
            us = db.session.get(UserStrategySetup, cid)
            if not us:
                return
            strat_obj = db.session.get(Strategy, us.strategy_id) if us.strategy_id else None
            sig = _compute_signal_for_user_strategy(us, strat_obj) if strat_obj and us else '-'
            rec = {'signal': sig, 'last_signal': sig, 'updated_at': int(time.time()*1000), 'symbol': us.symbol if us else ''}
            SIGNAL_CACHE[cid] = rec
            try:
                redis_set_signal(cid, rec)
            except Exception:
                pass
            # If this setup runs in paper mode and we have a BUY/SELL signal, process it immediately
            if getattr(us, 'is_paper', False) and sig in ('BUY', 'SELL'):
                    # try quick current price fetch
                    short = (us.symbol.split(':')[-1] if us.symbol else '').replace('_', '')
                    try:
                        cur_px = fetch_ltp_from_api(short)
                    except Exception:
                        cur_px = None
                    try:
                        process_paper_signal(us, sig, cur_px, strat_obj.name if strat_obj else None, trend_confirmed=True)
                        db.session.commit()
                    except Exception:
                        try:
                            db.session.rollback()
                        except Exception:
                            pass
        except Exception:
            pass

    # run processing in background to avoid blocking the request
    threading.Thread(target=process_user_strategy_start, args=(config_id,), daemon=True).start()
    return jsonify({'success': True, 'is_active': True, 'config_id': config_id})


@app.route('/algo_setup/<int:config_id>/stop', methods=['POST'])
@login_required
def stop_user_strategy(config_id):
    uid = session['user_id']
    strat = UserStrategySetup.query.filter_by(id=config_id, user_id=uid).first_or_404()
    strat.is_active = False
    db.session.commit()
    # spawn background cleanup task
    def _after_stop(cid):
        try:
            us = db.session.get(UserStrategySetup, cid)
            rec = {'signal': '-', 'last_signal': None, 'updated_at': int(time.time()*1000), 'symbol': us.symbol if us else ''}
            SIGNAL_CACHE[cid] = rec
            try:
                redis_set_signal(cid, rec)
            except Exception:
                pass
        except Exception:
            pass

    threading.Thread(target=_after_stop, args=(config_id,), daemon=True).start()
    return jsonify({'success': True, 'is_active': False, 'config_id': config_id})


@app.route('/algo_setup/<int:config_id>/paper_toggle', methods=['POST'])
@login_required
def toggle_paper_strategy(config_id):
    uid = session['user_id']
    strat = UserStrategySetup.query.filter_by(id=config_id, user_id=uid).first_or_404()
    # Toggle the is_paper flag
    strat.is_paper = not bool(strat.is_paper)
    db.session.commit()
    return jsonify({'success': True, 'is_paper': bool(strat.is_paper), 'config_id': config_id})

# ------------------ Backtester Routes ------------------
@app.route("/backtester", methods=["GET"], endpoint="backtester")
# @login_required
def backtester_page():
    uid = session["user_id"]
    user = db.session.get(User, session["user_id"])
    creds = Credentials.query.filter_by(user_id=user.id).first()

    # Build choices for the symbol select (fallback in case JS fails)
    choices = []
    try:
        actives = get_active_instruments_tv()  # returns [{label, tv}]
        choices = [(x["tv"], x["label"]) for x in actives][:300]
    except Exception:
        pass

    form = StrategyPopupForm()
    form.symbol_tv.choices = choices

    # User stats
    q = BacktestConfig.query.filter_by(user_id=uid)
    configs = q.order_by(BacktestConfig.created_at.desc()).all()
    total = len(configs)
    active = len([c for c in configs if c.is_active])
    profitable = 0
    this_month = 0

    # Last run per config for table
    table_rows = []
    for c in configs:
        last = (
            BacktestRun.query.filter_by(config_id=c.id, user_id=uid)
            .order_by(BacktestRun.id.desc())
            .first()
        )
        if last and last.pnl_inr > 0:
            profitable += 1
        if c.created_at.strftime("%Y-%m") == time.strftime("%Y-%m"):
            this_month += 1
        table_rows.append((c, last))

    stats = {
        "total": total,
        "active": active,
        "profitable": profitable,
        "this_month": this_month,
    }

    # Fetch all strategies for the dropdown in modal
    all_strategies = Strategy.query.filter_by(is_active=True).all()

    return render_template(
        "backtester.html",
        form=form,
        stats=stats,
        strategies=table_rows,
        all_strategies=all_strategies,
        user=user,
        creds=creds
    )


@app.route("/backtester/add", methods=["POST"], endpoint="add_backtest_strategy")
@login_required
def add_backtest_strategy():
    uid = session["user_id"]
    form = StrategyPopupForm()

    if not form.validate_on_submit():
        flash("Please fill all required fields correctly.", "danger")
        return redirect(url_for("backtester"))

    pair = tv_to_pair_market(form.symbol_tv.data)

    # Ensure correct type for dates (WTForms DateField gives datetime.date, but double-check)
    start_date = form.start_date.data
    end_date = form.end_date.data
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date, "%Y-%m-%d").date()

    cfg = BacktestConfig(
        user_id=uid,
        strategy_name=form.strategy_name.data.strip(),
        symbol_tv=form.symbol_tv.data,
        pair_market=pair,
        margin_in_inr=form.amount.data or 0.0,
        leverage=form.leverage.data or 0,
        timeframe=form.timeframe.data,
        start_date=form.start_date.data,  # ✅ WTForms DateField returns datetime.date already
        end_date=form.end_date.data,
        is_active=True
    )
    db.session.add(cfg)
    db.session.commit()
    flash("Strategy created.", "success")
    return redirect(url_for("backtester"))


@app.route("/backtester/<int:config_id>/edit", methods=["POST"], endpoint="edit_backtest_strategy")
@login_required
def edit_backtest_strategy(config_id):
    uid = session["user_id"]
    cfg = BacktestConfig.query.filter_by(id=config_id, user_id=uid).first_or_404()

    cfg.strategy_name = request.form.get("strategy_name", cfg.strategy_name)
    cfg.symbol_tv = request.form.get("symbol_tv", cfg.symbol_tv)
    cfg.pair_market = tv_to_pair_market(cfg.symbol_tv)
    cfg.margin_in_inr = float(request.form.get("amount", cfg.margin_in_inr) or 0)
    cfg.leverage = int(request.form.get("leverage", cfg.leverage) or 0)
    cfg.timeframe = request.form.get("timeframe", cfg.timeframe)

    # Convert dates safely
    start_date = request.form.get("start_date")
    end_date = request.form.get("end_date")
    if start_date:
        cfg.start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    if end_date:
        cfg.end_date = datetime.strptime(end_date, "%Y-%m-%d").date()

    db.session.commit()
    flash("Strategy updated.", "success")
    return redirect(url_for("backtester"))


@app.route("/backtester/<int:config_id>/delete", methods=["POST"], endpoint="delete_backtest_strategy")
@login_required
def delete_backtest_strategy(config_id):
    uid = session["user_id"]
    cfg = BacktestConfig.query.filter_by(id=config_id, user_id=uid).first_or_404()
    db.session.delete(cfg)
    db.session.commit()
    flash("Strategy deleted.", "warning")
    return redirect(url_for("backtester"))


@app.route("/backtester/<int:config_id>/run", methods=["POST"], endpoint="run_backtest")
@login_required
def run_backtest(config_id):
    uid = session["user_id"]
    cfg = BacktestConfig.query.filter_by(id=config_id, user_id=uid).first_or_404()

    # Mark run as "running"
    run = BacktestRun(config_id=cfg.id, user_id=uid, status="running")
    db.session.add(run)
    db.session.commit()

    try:
        # ✅ Call with config object
        result = run_backtest_dynamic(cfg)

        # Store run results
        run.status = "completed"
        run.finished_at = datetime.now(timezone.utc)
        run.trades = len(result["trades"])
        run.win_rate = result["metrics"].get("win_rate", 0.0)
        run.pnl_inr = result["metrics"].get("net_profit", 0.0)
        run.pnl_usdt = run.pnl_inr / max(usdt_inr_fx(), 1)
        run.metrics_json = json.dumps(result["metrics"])
        run.trades_json = json.dumps(result["trades"])
        run.equity_json = json.dumps(result["equity"])
        run.daily_json = json.dumps(result["daily"])
        run.monthly_json = json.dumps(result["monthly"])

        db.session.commit()

        flash("Backtest completed successfully.", "success")
        return redirect(url_for("backtest_results", run_id=run.id))

    except Exception as e:
        run.status = "failed"
        db.session.commit()
        flash(f"Backtest failed: {str(e)}", "danger")
        return redirect(url_for("backtester"))


@app.route("/backtester/results/<int:run_id>", methods=["GET"], endpoint="backtest_results")
@login_required
def backtest_results(run_id):
    uid = session["user_id"]
    run = BacktestRun.query.filter_by(id=run_id, user_id=uid).first_or_404()
    cfg = db.session.get(BacktestConfig, run.config_id)

    # ✅ Load JSONs directly
    metrics = json.loads(run.metrics_json or "{}")
    trades = json.loads(run.trades_json or "[]")
    equity_curve = json.loads(run.equity_json or "[]")
    daily_pnl = json.loads(run.daily_json or "{}")
    monthly_pnl = json.loads(run.monthly_json or "{}")

    return render_template(
        "backtest_results.html",
        cfg=cfg,
        run=run,
        metrics=metrics,
        trades=trades,
        equity_curve=equity_curve,
        daily_pnl=daily_pnl,
        monthly_pnl=monthly_pnl,
    )

# ------------------ Main ------------------
if __name__ == "__main__":
    import webbrowser, os
    from werkzeug.security import generate_password_hash

    with app.app_context():
        # --- Create tables ---
        db.create_all()

        # --- Seed Roles ---
        if not Role.query.filter_by(name="admin").first():
            db.session.add(Role(name="admin", description="Full access to the platform"))
        if not Role.query.filter_by(name="moderator").first():
            db.session.add(Role(name="moderator", description="Manages affiliates and earnings"))
        if not Role.query.filter_by(name="user").first():
            db.session.add(Role(name="user", description="Normal user"))
        db.session.commit()

        # --- Seed Admin User ---
        admin_role = Role.query.filter_by(name="admin").first()
        if not User.query.filter_by(email="asma.basha@gmail.com").first():
            admin_user = User(
                email="asma.basha@gmail.com",
                password=generate_password_hash("Admin@123"),
                role_id=admin_role.id
            )
            db.session.add(admin_user)
            db.session.commit()

        # --- Seed Moderator User ---
        mod_role = Role.query.filter_by(name="moderator").first()
        if not User.query.filter_by(email="aleena.air@gmail.com").first():
            mod_user = User(
                email="aleena.air@gmail.com",
                password=generate_password_hash("Moderator@123"),
                role_id=mod_role.id
            )
            db.session.add(mod_user)
            db.session.commit()

    # ✅ Open browser only once (on the reloader’s child process)
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        webbrowser.open("http://127.0.0.1:5000")

    # ✅ Always start the Flask server here
    # If the before_first_request registration failed earlier, ensure the
    # aggregator is started here as best-effort.
    try:
        _start_aggregator()
    except Exception:
        pass
    try:
        if os.environ.get('DISABLE_LTP_AGG', '0') != '1':
            start_ltp_poller(1)
    except Exception:
        pass

    app.run(debug=True)

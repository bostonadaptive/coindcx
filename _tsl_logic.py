#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CoinDCX Futures – Automated Trade Loop + Tables + TSL Toggle (Continuous / Step-wise) + Indicators Table + Multi-Symbol Adoption

Adds/changes:
- Startup toggle for TSL mode: Continuous OR Step-wise
- Continuous trailing: stop updates every favorable tick (max/min anchor)
- Step-wise trailing: stop trails only after each full TSL% move from the last anchor
- Adopts/monitors ANY already-open positions (all symbols). Closes on TSL hit; NO re-entry for non-selected symbols
- Re-entry remains only for the selected trading pair
- OPEN / PENDING / CLOSED printed as bordered tables
- New "Strategy — Indicators & Signal" bordered table for the selected pair (EMA9/EMA21/RSI/Lips/Teeth/Jaw + signal, live, pos, TSL Px)
"""

import os, json, time, hmac, hashlib, math, csv, sys
from typing import Any, Dict, List, Optional, Tuple
from decimal import Decimal, ROUND_DOWN

import requests
from dotenv import load_dotenv

_mcp_base = os.getenv('COINDCX_MCP') or os.getenv('COINDCX_PROXY')
API_BASE    = os.getenv('COINDCX_API_BASE') or _mcp_base or "https://api.coindcx.com"
PUBLIC_BASE = os.getenv('COINDCX_PUBLIC_BASE') or _mcp_base or "https://public.coindcx.com"

# ====== CONFIG ======
POLL_SEC                = 6
QUERY_MODES             = [s.strip().upper() for s in os.getenv("COINDCX_MARGIN_QUERY", "INR,USDT").split(",") if s.strip()]
MARGIN_MODE             = os.getenv("COINDCX_MARGIN_MODE", "INR").upper()
POSITION_MARGIN         = "isolated"
USDTINR_FALLBACK        = 89.0
MARGIN_SAFETY           = 0.995
TRADES_CSV_PATH         = os.getenv("COINDCX_TRADES_CSV", "trades_all.csv")
ORDERS_PAGES_FILLED     = int(os.getenv("COINDCX_ORDERS_PAGES_FILLED", "12"))
OPEN_SUPPRESS_AGE_DAYS  = int(os.getenv("COINDCX_OPEN_AGE_DAYS", "120"))
HIST_MINUTES            = int(os.getenv("COINDCX_HIST_MINUTES", "600"))
SIGNAL_COOLDOWN_MIN     = int(os.getenv("COINDCX_SIGNAL_COOLDOWN_MIN", "1"))

# ====== PRE-TRADE VALIDATION (tunable) ======
ENTRY_SR_NEAR_PCT            = float(os.getenv("COINDCX_ENTRY_SR_NEAR_PCT", "0.004"))  # 0.4% from S/R blocks entry unless breakout
DONCHIAN_LOOKBACK            = int(os.getenv("COINDCX_DONCHIAN_LOOKBACK", "40"))       # S/R window (minutes)
TREND_EMA_SPREAD_MIN         = float(os.getenv("COINDCX_TREND_EMA_SPREAD_MIN", "0.001"))  # S1: 0.1% EMA9/21 separation
TREND_RSI_LONG_MIN           = float(os.getenv("COINDCX_TREND_RSI_LONG_MIN", "58"))      # S1: RSI floor for longs
TREND_RSI_SHORT_MAX          = float(os.getenv("COINDCX_TREND_RSI_SHORT_MAX", "42"))      # S1: RSI ceiling for shorts
TREND_S2_MD_SB_RATIO_MIN     = float(os.getenv("COINDCX_TREND_S2_MD_SB_RATIO_MIN", "1.0"))  # S2: |MD| / |SignalBase| >= 1

# ====== S3 (MA Cross) tunables ======
MA_SHORT_LEN            = int(os.getenv("COINDCX_MA_SHORT_LEN", "9"))
MA_LONG_LEN             = int(os.getenv("COINDCX_MA_LONG_LEN", "21"))
MA_FLAT_GAP_PCT         = float(os.getenv("COINDCX_MA_FLAT_GAP_PCT", "0.0007"))  # ~0.07% = chop when MAs too close
MA_CHOP_LOOKBACK        = int(os.getenv("COINDCX_MA_CHOP_LOOKBACK", "5"))        # last K candles
MA_CHOP_MIN_BODY_TOUCH  = int(os.getenv("COINDCX_MA_CHOP_MIN_BODY_TOUCH", "3"))  # candles where MA lies inside body
MA_CHOP_MAX_WICK_TOUCH  = int(os.getenv("COINDCX_MA_CHOP_MAX_WICK_TOUCH", "1"))  # candles where MA lies inside wick


# ====== Keys / Session ======
load_dotenv()
API_KEY    = os.getenv("COINDCX_API_KEY", "").strip()
API_SECRET = os.getenv("COINDCX_API_SECRET", "").strip()

session = requests.Session()
session.headers.update({"Content-Type": "application/json"})

# ====== Util ======
def _now_ms() -> int:
    return int(round(time.time() * 1000))

def _sign(body: dict) -> Tuple[str, str]:
    payload = json.dumps(body, separators=(",", ":"))
    sig = hmac.new(API_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return sig, payload

def ex_post(path: str, body: dict) -> Any:
    sig, payload = _sign(body)
    headers = {"X-AUTH-APIKEY": API_KEY, "X-AUTH-SIGNATURE": sig, "Content-Type": "application/json"}
    r = session.post(API_BASE + path, data=payload, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()

def ex_post_soft(path: str, body: dict) -> Optional[Any]:
    sig, payload = _sign(body)
    headers = {"X-AUTH-APIKEY": API_KEY, "X-AUTH-SIGNATURE": sig, "Content-Type": "application/json"}
    try:
        r = session.post(API_BASE + path, data=payload, headers=headers, timeout=30)
        if r.status_code == 422:
            return None
        r.raise_for_status()
        return r.json()
    except requests.HTTPError:
        return None

def ex_get_signed(path: str, body: dict) -> Any:
    sig, payload = _sign(body)
    headers = {"X-AUTH-APIKEY": API_KEY, "X-AUTH-SIGNATURE": sig, "Content-Type": "application/json"}
    r = session.get(API_BASE + path, data=payload, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()

def ms_to_utc(ms_like: Any) -> str:
    try:
        if ms_like in (None, "", 0, "0"):
            return "-"
        v = int(float(ms_like))
        if v < 10_000_000_000: v *= 1000
        if v <= 0: return "-"
        return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(v/1000))
    except Exception:
        return "-"

def _to_ms(ts_like: Any) -> float:
    try:
        v = float(ts_like)
        if v < 10_000_000_000: v *= 1000.0
        return v
    except Exception:
        return 0.0

def safe_float(d: dict, keys: List[str], default: float=float("nan")) -> float:
    for k in keys:
        if k in d and d[k] not in (None, "", "nan"):
            try: return float(d[k])
            except Exception: pass
    return default

def safe_str(d: dict, keys: List[str], default: str="-") -> str:
    for k in keys:
        v = d.get(k)
        if v not in (None, ""): return str(v)
    return default

def try_float(x) -> float:
    try: return float(x)
    except Exception: return float("nan")

# ====== Public / Market Data ======
def active_instruments(margin_mode: str) -> List[str]:
    url = API_BASE + "/exchange/v1/derivatives/futures/data/active_instruments"
    r = session.get(url, params={"margin_currency_short_name[]": margin_mode}, timeout=30)
    r.raise_for_status()
    js = r.json()
    out: List[str] = []
    if isinstance(js, list):
        for it in js:
            if isinstance(it, str): out.append(it)
            elif isinstance(it, dict) and it.get("market"): out.append(it["market"])
    return sorted(out)

def instrument_detail(pair: str, margin_mode: str) -> Dict[str, Any]:
    url = API_BASE + "/exchange/v1/derivatives/futures/data/instrument"
    r = session.get(url, params={"pair": pair, "margin_currency_short_name": margin_mode}, timeout=30)
    r.raise_for_status()
    js = r.json()
    if isinstance(js, dict):
        if isinstance(js.get("instrument"), dict): return js["instrument"]
        if isinstance(js.get("data"), list) and js["data"]: return js["data"][0]
    return {}

def last_price_usdt(pair: str) -> float:
    try:
        # import centralized LTP helper and prefer a fresh (signed/authoritative) price
        from ltp import last_price_usdt as _ltp_fn
        return _ltp_fn(pair, prefer_mark_for_valuation=True, force_refresh=True)
    except Exception:
        # fallback to local instrument detail -> candles
        try:
            det = instrument_detail(pair, MARGIN_MODE)
            for k in ("mark_price", "last_price", "index_price"):
                if k in det and det[k] not in (None, "", 0, "0"): return float(det[k])
        except Exception:
            pass
        try:
            end_sec = int(time.time()); start_sec = end_sec - 8*60
            r = session.get(PUBLIC_BASE + "/market_data/candlesticks",
                            params={"pair": pair, "from": start_sec, "to": end_sec, "resolution":"1", "pcode":"f"},
                            timeout=30)
            r.raise_for_status()
            rows = (r.json() or {}).get("data") or []
            return float(rows[-1]["close"]) if rows else float("nan")
        except Exception:
            return float("nan")

def usdt_inr_fx() -> float:
    try:
        r = session.get("https://api.exchangerate.host/convert", params={"from":"USD","to":"INR"}, timeout=10)
        r.raise_for_status()
        js = r.json()
        if isinstance(js, dict) and js.get("result"):
            return float(js["result"])
    except Exception:
        pass
    return USDTINR_FALLBACK

# ===== Timeframes & Candle Fetch (generic) =====
TIMEFRAME_MINUTES = {
    "1m": 1, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "8h": 480,
}
# Ladder for higher-timeframe confirmation (None means no higher TF)
NEXT_HIGHER_TF = {
    "1m": "5m", "5m": "15m", "15m": "30m", "30m": "1h",
    "1h": "2h", "2h": "4h", "4h": "8h", "8h": None,
}

def fetch_candles_tf(pair: str, tf_label: str, bars: int) -> List[dict]:
    """Fetch 'bars' OHLCV candles for the given timeframe label (e.g., '5m', '1h')."""
    tf_min = TIMEFRAME_MINUTES[tf_label]
    end_sec = int(time.time())
    start_sec = end_sec - bars * tf_min * 60
    r = session.get(
        PUBLIC_BASE + "/market_data/candlesticks",
        params={
            "pair": pair,
            "from": start_sec,
            "to": end_sec,
            "resolution": str(tf_min),  # CoinDCX expects minutes as string
            "pcode": "f",
        },
        timeout=30
    )
    r.raise_for_status()
    data = (r.json() or {}).get("data") or []
    out = []
    for row in data:
        t = int(row.get("time") or row.get("t") or 0)
        if t < 10_000_000_000:
            t *= 1000
        out.append({
            "ts": t,
            "o": float(row.get("open", 0.0)),
            "h": float(row.get("high", 0.0)),
            "l": float(row.get("low", 0.0)),
            "c": float(row.get("close", 0.0)),
            "v": float(row.get("volume", 0.0)),
        })
    out.sort(key=lambda x: x["ts"])
    return out

def refresh_candles_dedupe(pair: str, tf_label: str, existing: List[dict], recent_bars: int) -> List[dict]:
    """Fetch a small recent window and merge/dedupe by timestamp."""
    try:
        recent = fetch_candles_tf(pair, tf_label, max(recent_bars, 20))
        idx = {c["ts"]: c for c in (existing or [])}
        for c in recent:
            idx[c["ts"]] = c
        merged = [idx[k] for k in sorted(idx.keys())]
        return merged
    except Exception:
        return existing or []


# ====== Indicators ======
def ema(values: List[float], period: int) -> List[float]:
    out = []; k = 2.0/(period+1.0); ema_val = None
    for v in values:
        ema_val = v if ema_val is None else (v - ema_val)*k + ema_val
        out.append(ema_val)
    return out

def smma(values: List[float], period: int) -> List[float]:
    out = []; sm = None
    for i, v in enumerate(values):
        if sm is None:
            sm = v if i+1 < period else sum(values[i-period+1:i+1])/period
        else:
            sm = (sm*(period-1) + v)/period
        out.append(sm)
    return out

def rsi(values: List[float], period: int=14) -> List[float]:
    rsis = []; gains = losses = 0.0; prev = None; avg_gain = avg_loss = None
    for i, v in enumerate(values):
        if prev is None:
            rsis.append(50.0); prev = v; continue
        chg = v - prev; gain = max(chg, 0.0); loss = -min(chg, 0.0)
        if i < period:
            gains += gain; losses += loss; rsis.append(50.0)
        elif i == period:
            gains += gain; losses += loss; avg_gain = gains/period; avg_loss = losses/period
            rs = (avg_gain/avg_loss) if avg_loss > 0 else float('inf')
            rsis.append(100.0 - 100.0/(1.0+rs))
        else:
            avg_gain = (avg_gain*(period-1) + gain)/period
            avg_loss = (avg_loss*(period-1) + loss)/period
            rs = (avg_gain/avg_loss) if avg_loss > 0 else float('inf')
            rsis.append(100.0 - 100.0/(1.0+rs))
        prev = v
    return rsis

def build_indicators(candles: List[dict]) -> None:
    if not candles: return
    closes  = [c["c"] for c in candles]
    medians = [(c["h"] + c["l"]) / 2.0 for c in candles]
    ema9  = ema(closes, 9); ema21 = ema(closes, 21); rsi14 = rsi(closes, 14)
    jaw   = smma(medians, 13); teeth = smma(medians, 8); lips = smma(medians, 5)
    for i, c in enumerate(candles):
        c["ema9"]  = ema9[i]; c["ema21"] = ema21[i]; c["rsi14"] = rsi14[i]
        c["jaw"]   = jaw[i];  c["teeth"] = teeth[i]; c["lips"]  = lips[i]

# ---------- Strategy 3 (MA Cross 9/21) ----------
def build_indicators_s3(candles: List[dict]) -> None:
    """Attach SMA(9) and SMA(21) to candles as sma_s and sma_l."""
    if not candles: return
    closes = [c["c"] for c in candles]
    sma_s  = sma(closes, MA_SHORT_LEN)
    sma_lg = sma(closes, MA_LONG_LEN)
    for i, c in enumerate(candles):
        c["sma_s"] = sma_s[i]
        c["sma_l"] = sma_lg[i]

def _body_low_high(c: dict) -> Tuple[float,float]:
    lo = min(c["o"], c["c"])
    hi = max(c["o"], c["c"])
    return lo, hi

def _ma_in_body(c: dict, ma_val: float) -> bool:
    lo, hi = _body_low_high(c)
    return lo <= ma_val <= hi

def _gap_pct(p: float, q: float) -> float:
    base = max(abs(q), 1e-12)
    return abs(p - q) / base

def _is_choppy_ma(candles: List[dict]) -> bool:
    """Sideways: MA pair inside bodies too often and/or gap too tiny."""
    n = len(candles)
    if n < MA_CHOP_LOOKBACK + 2: return True
    block = candles[-(MA_CHOP_LOOKBACK+1):-1]  # completed only
    touches = 0
    tiny_gap_hits = 0
    for c in block:
        ss = c.get("sma_s", float("nan"))
        ll = c.get("sma_l", float("nan"))
        if not (is_posfinite(ss) and is_posfinite(ll)): 
            return True
        if _ma_in_body(c, ss) or _ma_in_body(c, ll):
            touches += 1
        if _gap_pct(ss, ll) <= MA_FLAT_GAP_PCT:
            tiny_gap_hits += 1
    return (touches >= MA_CHOP_MIN_BODY_TOUCH) or (tiny_gap_hits >= (MA_CHOP_LOOKBACK // 2 + 1))

def _last_cross_idx(candles: List[dict]) -> Tuple[Optional[int], Optional[str]]:
    """Return (idx, 'bull'/'bear') for last completed-bar cross of SMA9 over SMA21."""
    n = len(candles)
    if n < 4: return None, None
    # use completed bars only
    for i in range(n-3, 0, -1):
        s0, l0 = candles[i-1].get("sma_s"), candles[i-1].get("sma_l")
        s1, l1 = candles[i].get("sma_s"), candles[i].get("sma_l")
        if not all(map(is_posfinite, [s0,l0,s1,l1])): 
            continue
        if s0 <= l0 and s1 > l1:
            return i, "bull"
        if s0 >= l0 and s1 < l1:
            return i, "bear"
    return None, None

def _first_untouched_after(candles: List[dict], i_cross: int, side: str) -> Optional[int]:
    """
    Find the very first candle after cross where the BODY does not touch either MA and is on the correct side:
      - BUY: body entirely ABOVE both MAs
      - SELL: body entirely BELOW both MAs
    """
    n = len(candles)
    end = n - 1  # exclude forming
    for j in range(i_cross+1, end):
        c = candles[j]
        ss, ll = c.get("sma_s"), c.get("sma_l")
        if not all(map(is_posfinite, [ss, ll])): 
            continue
        lo, hi = _body_low_high(c)
        touches = (lo <= ss <= hi) or (lo <= ll <= hi)
        if touches: 
            continue
        if side == "long":
            if lo > max(ss, ll):
                return j
        else:
            if hi < min(ss, ll):
                return j
    return None

def signal_strategy3(candles: List[dict]) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Pine logic replicated:
      - Detect cross (SMA9↗SMA21 => BUY; SMA9↘SMA21 => SELL).
      - Find the very first 'untouched' candle after cross (body not touching either MA and on correct side).
      - Entry triggers when a subsequent completed candle closes beyond that untouched candle’s extreme:
          BUY  when close > untouched_high
          SELL when close < untouched_low
      - Ignore if choppy (indicator overlying bodies / tiny gap).
    """
    info: Dict[str, Any] = {"s3_cross": "-", "s3_untouched_hi": "-", "s3_untouched_lo": "-", "s3_break": "-", "s3_chop": "-"}
    n = len(candles)
    if n < 10: return None, info

    if _is_choppy_ma(candles):
        info["s3_chop"] = "yes"
        return None, info
    info["s3_chop"] = "no"

    i_cross, cside = _last_cross_idx(candles)
    if i_cross is None:
        return None, info
    side = "long" if cside == "bull" else "short"
    info["s3_cross"] = "BULL" if side == "long" else "BEAR"

    j = _first_untouched_after(candles, i_cross, side)
    if j is None:
        return None, info

    untouched = candles[j]
    u_lo, u_hi = _body_low_high(untouched)
    info["s3_untouched_hi"] = f"{u_hi:.4f}"
    info["s3_untouched_lo"] = f"{u_lo:.4f}"

    # trigger on last completed candle
    k = n - 2
    last = candles[k]
    if side == "long":
        info["s3_break"] = f">{u_hi:.4f}"
        if last["c"] > u_hi:
            return "long", info
    else:
        info["s3_break"] = f"<{u_lo:.4f}"
        if last["c"] < u_lo:
            return "short", info

    return None, info

def is_signal_active_s3(side: str, last_c: dict, live_px: float) -> bool:
    """Live guard: price should remain on the correct side of both MAs."""
    if not is_posfinite(live_px): return False
    ss = last_c.get("sma_s", float("nan"))
    ll = last_c.get("sma_l", float("nan"))
    if not all(map(is_posfinite, [ss, ll])): return False
    if side == "long":
        return live_px > max(ss, ll)
    return live_px < min(ss, ll)

# ====== Wallets & Orders ======
def futures_wallets() -> Any:
    return ex_get_signed("/exchange/v1/derivatives/futures/wallets", {"timestamp": _now_ms()})

def get_free_balances() -> Tuple[float, float]:
    """Return (free_inr, free_usdt). Falls back to (0.0, 0.0) on error."""
    try:
        js = futures_wallets()
        items = []
        if isinstance(js, list):
            items = js
        elif isinstance(js, dict):
            for k in ("wallets", "data", "balances"):
                if isinstance(js.get(k), list):
                    items = js[k]; break
        free_map = {"INR": 0.0, "USDT": 0.0}
        for it in items:
            sym = (it.get("currency_short_name") or it.get("currency") or it.get("asset") or "").upper()
            if sym in free_map:
                free_map[sym] = float(it.get("free_balance") or it.get("available_balance") or it.get("balance") or 0.0)
        return free_map["INR"], free_map["USDT"]
    except Exception:
        return 0.0, 0.0

def futures_list_orders(status_csv: str, page=1, size=200, soft=False) -> List[dict]:
    body: Dict[str, Any] = {
        "timestamp": _now_ms(),
        "status": status_csv,
        "page": str(page),
        "size": str(size),
        "margin_currency_short_name": QUERY_MODES,
    }
    resp = ex_post_soft("/exchange/v1/derivatives/futures/orders", body) if soft else ex_post("/exchange/v1/derivatives/futures/orders", body)
    if not resp: return []
    if isinstance(resp, list): return resp
    if isinstance(resp, dict):
        for k in ("orders","data"):
            if isinstance(resp.get(k), list): return resp[k]
    return []

def fetch_orders_paginated(status_csv: str, max_pages: int, size: int = 200) -> List[dict]:
    out: List[dict] = []; seen: set = set()
    for p in range(1, max_pages + 1):
        chunk = futures_list_orders(status_csv, page=p, size=size, soft=True)
        if not chunk: break
        for o in chunk:
            oid = str(o.get("id") or "")
            if not oid or oid in seen: continue
            seen.add(oid); out.append(o)
        if len(chunk) < size: break
    return out

def fetch_all_orders() -> List[dict]:
    combined: List[dict] = []
    combined += fetch_orders_paginated("initial,open,partially_filled,untriggered", max_pages=1)
    combined += fetch_orders_paginated("filled", max_pages=ORDERS_PAGES_FILLED)
    combined += fetch_orders_paginated("cancelled,rejected,closed", max_pages=1)
    seen: set = set(); out: List[dict] = []
    for o in combined:
        oid = str(o.get("id") or "")
        if not oid or oid in seen: continue
        seen.add(oid); out.append(o)
    return out

def create_futures_market_order(pair: str, side: str, qty: float, lev: int) -> Any:
    # Safety: block real order placement unless explicitly enabled via env
    # This prevents accidental trades during development/testing.
    try:
        if os.environ.get('ALLOW_REAL_TRADES', '0') != '1':
            raise RuntimeError('Real order placement disabled by ALLOW_REAL_TRADES')
    except Exception:
        # If env parsing fails, err on the side of safety by disallowing orders
        raise RuntimeError('Real order placement disabled by ALLOW_REAL_TRADES')
    body = {
        "timestamp": _now_ms(),
        "order": {
            "side": side,
            "pair": pair,
            "order_type": "market_order",
            "total_quantity": qty,
            "leverage": lev,
            "hidden": False,
            "post_only": False,
            "notification": "no_notification",
            "margin_currency_short_name": MARGIN_MODE,
            "position_margin_type": POSITION_MARGIN
        }
    }
    return ex_post("/exchange/v1/derivatives/futures/orders/create", body)

# ====== Bordered Table Helpers ======
def _calc_col_widths(rows: List[Dict[str, Any]], columns: List[Tuple[str, str]]) -> List[int]:
    widths = [len(h) for h, _ in columns]
    for r in rows:
        for i, (_, key) in enumerate(columns):
            widths[i] = max(widths[i], len(str(r.get(key, ""))))
    return widths

def _print_bordered_table(title: str, rows: List[Dict[str, Any]], columns: List[Tuple[str, str]]):
    print("\n" + title)
    title_line = "+" + "-"*(len(title)+2) + "+"
    # print(title_line)  # optional border around title
    if not rows:
        print("(none)")
        return
    widths = _calc_col_widths(rows, columns)
    def sep(char: str = "-"):
        return "+" + "+".join(char*(w+2) for w in widths) + "+"
    print(sep("-"))
    # header
    header_cells = [" " + h.ljust(w) + " " for (h, _), w in zip(columns, widths)]
    print("|" + "|".join(header_cells) + "|")
    print(sep("="))
    # rows
    for r in rows:
        cells = [" " + str(r.get(key, "")).ljust(w) + " " for (_, key), w in zip(columns, widths)]
        print("|" + "|".join(cells) + "|")
        print(sep("-"))

def export_csv(path: str, rows: List[Dict[str, Any]], columns: List[Tuple[str, str]]):
    try:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([hdr for hdr, _ in columns])
            for r in rows:
                writer.writerow([(r.get(key, "") if r.get(key) is not None else "") for _, key in columns])
        print(f"[csv] wrote {len(rows)} rows to {path}")
    except Exception as e:
        print(f"[csv] error writing {path}: {e}")

# ====== Normalizers / Pairing ======
def _first_key(d: dict, keys: List[str]) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""): return d[k]
    return None

def normalize_order(o: dict) -> Dict[str, Any]:
    qty_total  = safe_float(o, ["total_quantity","quantity","orig_qty"], 0.0)
    qty_filled = safe_float(o, ["filled_quantity","executed_qty","filledQuantity"], float("nan"))
    avg = safe_float(o, ["avg_price","price"], 0.0)
    lev = safe_float(o, ["leverage"], float("nan"))
    created_raw = _first_key(o, ["created_at","timestamp","time"])
    updated_raw = _first_key(o, ["updated_at","last_update_time"])
    return {
        "id":         safe_str(o, ["id"]),
        "pair":       safe_str(o, ["pair"]),
        "side":       safe_str(o, ["side"]).lower(),
        "status":     safe_str(o, ["status"]).lower(),
        "qty":        f"{qty_total:.6f}",
        "qty_num":    0.0 if math.isnan(qty_total) else float(qty_total),
        "filled":     (f"{qty_filled:.6f}" if not math.isnan(qty_filled) else "-"),
        "avg_price":  f"{avg:.6f}",
        "price_num":  0.0 if math.isnan(avg) else float(avg),
        "lev":        (f"{int(lev)}x" if not math.isnan(lev) else "-"),
        "created_at": ms_to_utc(created_raw),
        "updated_at": ms_to_utc(updated_raw),
        "created_at_raw": created_raw,
        "updated_at_raw": updated_raw,
    }

def derive_from_trades(all_orders_norm: List[Dict[str, Any]], fx_inr: float) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    fills: List[Dict[str, Any]] = []
    for r in all_orders_norm:
        if r.get("status") != "filled": continue
        qty = float(r.get("qty_num") or 0.0); px  = float(r.get("price_num") or 0.0)
        if qty <= 0 or px <= 0: continue
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
        if pair not in per_pair: per_pair[pair] = {"buys": [], "sells": []}
        buys = per_pair[pair]["buys"]; sells = per_pair[pair]["sells"]

        qty_rem = f["qty"]
        if f["side"] == "buy":
            while qty_rem > 0 and sells:
                s = sells[0]; match = min(qty_rem, s["qty"])
                pnl_usdt = (s["price"] - f["price"]) * match
                closed.append({
                    "id": f"{s['id']}->{f['id']}", "pair": pair, "side": "short",
                    "qty": f"{match:.6f}", "entry_px": f"{s['price']:.6f}", "exit_px": f"{f['price']:.6f}",
                    "lev": s["lev"], "entry_ms": s["t_ms"], "exit_ms": f["t_ms"],
                    "entry_at": ms_to_utc(s["t_ms"]), "exit_at": ms_to_utc(f["t_ms"]),
                    "pnl_usdt": pnl_usdt,
                        "pnl_inr_value": (round((pnl_usdt * fx_inr), 2) if pnl_usdt==pnl_usdt else None),
                        "pnl_inr": (round((pnl_usdt * fx_inr), 2) if pnl_usdt==pnl_usdt else None),
                        "pnl_inr_str": (f"{(pnl_usdt * fx_inr):.2f} INR" if pnl_usdt==pnl_usdt else None),
                })
                s["qty"] -= match; qty_rem -= match
                if s["qty"] <= 1e-15: sells.pop(0)
            if qty_rem > 1e-15:
                buys.append({"id": f["id"], "price": f["price"], "qty": qty_rem, "lev": f["lev"], "t_ms": f["t_ms"]})
        else:
            while qty_rem > 0 and buys:
                b = buys[0]; match = min(qty_rem, b["qty"])
                pnl_usdt = (f["price"] - b["price"]) * match
                closed.append({
                    "id": f"{b['id']}->{f['id']}", "pair": pair, "side": "long",
                    "qty": f"{match:.6f}", "entry_px": f"{b['price']:.6f}", "exit_px": f"{f['price']:.6f}",
                    "lev": b["lev"], "entry_ms": b["t_ms"], "exit_ms": f["t_ms"],
                    "entry_at": ms_to_utc(b["t_ms"]), "exit_at": ms_to_utc(f["t_ms"]),
                    "pnl_usdt": pnl_usdt,
                        "pnl_inr_value": (round((pnl_usdt * fx_inr), 2) if pnl_usdt==pnl_usdt else None),
                        "pnl_inr": (round((pnl_usdt * fx_inr), 2) if pnl_usdt==pnl_usdt else None),
                        "pnl_inr_str": (f"{(pnl_usdt * fx_inr):.2f} INR" if pnl_usdt==pnl_usdt else None),
                })
                b["qty"] -= match; qty_rem -= match
                if b["qty"] <= 1e-15: buys.pop(0)
            if qty_rem > 1e-15:
                sells.append({"id": f["id"], "price": f["price"], "qty": qty_rem, "lev": f["lev"], "t_ms": f["t_ms"]})

    open_rows: List[Dict[str, Any]] = []
    now_ms = _now_ms(); cutoff_ms = now_ms - OPEN_SUPPRESS_AGE_DAYS * 24 * 60 * 60 * 1000

    for pair, q in per_pair.items():
        if q["buys"]:
            tot_qty = sum(x["qty"] for x in q["buys"])
            if tot_qty > 1e-12:
                first_t = min(x["t_ms"] for x in q["buys"])
                if first_t >= cutoff_ms:
                    vwap = sum(x["qty"]*x["price"] for x in q["buys"]) / tot_qty
                    lev0 = q["buys"][0]["lev"]; mark = last_price_usdt(pair, prefer_mark_for_valuation=True)
                    pnl_usdt = (mark - vwap) * tot_qty if not math.isnan(mark) else float("nan")
                    open_rows.append({
                        "id": q["buys"][0]["id"], "pair": pair, "side": "long",
                        "qty": f"{tot_qty:.6f}", "entry_px": f"{vwap:.6f}",
                        "mark_px": f"{(mark if not math.isnan(mark) else 0.0):.6f}" if not math.isnan(mark) else "-",
                        "lev": lev0,
                        "pnl_open_inr_value": None if pnl_usdt!=pnl_usdt else round((pnl_usdt*fx_inr),2),
                            "pnl_open_inr": None if pnl_usdt!=pnl_usdt else round((pnl_usdt*fx_inr),2),
                            "pnl_open_inr_str": "-" if pnl_usdt!=pnl_usdt else f"{(pnl_usdt*fx_inr):.2f} INR",
                        "entry_at": ms_to_utc(first_t), "updated_at": ms_to_utc(max(x["t_ms"] for x in q["buys"]))
                    })
        if q["sells"]:
            tot_qty = sum(x["qty"] for x in q["sells"])
            if tot_qty > 1e-12:
                first_t = min(x["t_ms"] for x in q["sells"])
                if first_t >= cutoff_ms:
                    vwap = sum(x["qty"]*x["price"] for x in q["sells"]) / tot_qty
                    lev0 = q["sells"][0]["lev"]; mark = last_price_usdt(pair, prefer_mark_for_valuation=True)
                    pnl_usdt = (vwap - mark) * tot_qty if not math.isnan(mark) else float("nan")
                    open_rows.append({
                        "id": q["sells"][0]["id"], "pair": pair, "side": "short",
                        "qty": f"{tot_qty:.6f}", "entry_px": f"{vwap:.6f}",
                        "mark_px": f"{(mark if not math.isnan(mark) else 0.0):.6f}" if not math.isnan(mark) else "-",
                        "lev": lev0, "pnl_open_inr": None if pnl_usdt!=pnl_usdt else round((pnl_usdt*fx_inr),2), "pnl_open_inr_str": "-" if pnl_usdt!=pnl_usdt else f"{(pnl_usdt*fx_inr):.2f} INR",
                        "entry_at": ms_to_utc(first_t), "updated_at": ms_to_utc(max(x["t_ms"] for x in q["sells"]))
                    })

    open_rows.sort(key=lambda r: (r["pair"], r["side"]))
    closed.sort(key=lambda r: r["exit_ms"], reverse=True)
    closed_last15 = closed[:5]
    for c in closed_last15: c["pnl_usdt"] = f"{c['pnl_usdt']:.6f} USDT"
    return open_rows, closed_last15

# ====== Sizing + input ======
def snap_qty(qty: float, inc: float, min_q: float) -> float:
    inc_d = Decimal(str(inc if inc else 1)); qd = Decimal(str(qty))
    snapped = (qd / inc_d).to_integral_value(rounding=ROUND_DOWN) * inc_d
    val = float(snapped)
    if val < (min_q or float(inc_d)): val = float(min_q or float(inc_d))
    return float(Decimal(str(val)).quantize(inc_d))

def qty_from_margin_in_inr(margin_in_inr: float, leverage: int, price_usdt: float, usdtinr: float) -> float:
    margin_usdt = float(margin_in_inr) / float(usdtinr)
    return (margin_usdt * float(leverage)) / max(float(price_usdt), 1e-12)

def ask_choice(prompt: str, choices: Dict[str, str], default_key: Optional[str]=None) -> str:
    while True:
        print(prompt)
        for k, label in choices.items(): print(f"{k}. {label}")
        ans = input(f"Enter choice [{'/'.join(choices.keys())}]{' default '+default_key if default_key else ''}: ").strip()
        if not ans and default_key: return default_key
        if ans in choices: return ans
        print("Invalid choice; try again.")

# Finite & positive checker (for prices, qty, etc.)
def is_posfinite(x) -> bool:
    try:
        v = float(x)
        return math.isfinite(v) and v > 0.0
    except Exception:
        return False

# ---------- Strategy 1 (EMA/RSI + Alligator) ----------
# Reuse your existing EMA/RSI/SMMA and build_indicators from above.

def build_indicators_s1(candles: List[dict]) -> None:
    """Alias for S1 to reuse the existing indicator builder."""
    build_indicators(candles)

def signal_strategy1(c: dict) -> Optional[str]:
    if (c["ema9"] > c["ema21"]) and (c["rsi14"] > 55.0) and (c["lips"] > c["teeth"] > c["jaw"]):
        return "long"
    if (c["ema9"] < c["ema21"]) and (c["rsi14"] < 45.0) and (c["lips"] < c["teeth"] < c["jaw"]):
        return "short"
    return None

def strong_s1(c: dict) -> Optional[str]:
    ema_spread = abs(c["ema9"] - c["ema21"]) / max(1e-12, c["ema21"])
    if (c["ema9"] > c["ema21"]) and (c["rsi14"] >= 62.0) and (c["lips"] > c["teeth"] > c["jaw"]) and (ema_spread >= 0.001):
        return "long"
    if (c["ema9"] < c["ema21"]) and (c["rsi14"] <= 38.0) and (c["lips"] < c["teeth"] < c["jaw"]) and (ema_spread >= 0.001):
        return "short"
    return None

# ---------- Strategy 2 (TSA + iMACD) ----------
def sma(values: List[float], period: int) -> List[float]:
    out, q, s = [], [], 0.0
    for v in values:
        q.append(v); s += v
        if len(q) > period: s -= q.pop(0)
        out.append(s / len(q))
    return out

def wma(values: List[float], period: int) -> List[float]:
    out, weights = [], list(range(1, period + 1))
    wsum = sum(weights)
    for i in range(len(values)):
        if i + 1 < period:
            sub = values[:i + 1]; wts = list(range(1, len(sub) + 1))
            out.append(sum(a*b for a, b in zip(sub, wts)) / sum(wts))
        else:
            sub = values[i - period + 1:i + 1]
            out.append(sum(a*b for a, b in zip(sub, weights)) / wsum)
    return out

def zlema(values: List[float], period: int) -> List[float]:
    e1 = ema(values, period); e2 = ema(e1, period)
    return [a + (a - b) for a, b in zip(e1, e2)]

def compute_tsa(closes: List[float]) -> Tuple[Optional[str], Dict[str, float]]:
    n = len(closes)
    if n < 5: return None, {}
    dyn = [float('nan')] * n
    deltas = [abs(closes[i] - closes[i-1]) if i > 0 else 0.0 for i in range(n)]
    for i in range(n):
        counts = closes[i]; prev = closes[i-1] if i > 0 else closes[i]
        max_abs = max(1.0, max(abs(closes[j]) for j in range(max(0, i-199), i+1)))
        norm = (counts + max_abs) / (2.0 * max_abs)
        dyn_len = 5.0 + norm * (50.0 - 5.0)
        max_delta = max(1e-12, max(deltas[max(0, i-199):i+1]))
        acc_fac = abs(counts - prev) / max_delta
        alpha = min(1.0, (2.0 / (dyn_len + 1.0)) * (1.0 + acc_fac * 5.0))
        dyn[i] = counts if (i == 0 or math.isnan(dyn[i-1])) else alpha * counts + (1.0 - alpha) * dyn[i-1]
    w2 = wma(closes, 2)
    i = n - 2
    side = "long" if w2[i] > dyn[i] else ("short" if w2[i] < dyn[i] else None)
    return side, {"tsa_dyn_ema": dyn[i], "tsa_wma2": w2[i],
                  "tsa_side": ("BUY" if side == "long" else "SELL" if side == "short" else "No Trade")}

def imacd(highs: List[float], lows: List[float], closes: List[float]) -> Tuple[Optional[str], Dict[str, float]]:
    n = len(closes)
    if n < 5: return None, {}
    src = [(h + l + c) / 3.0 for h, l, c in zip(highs, lows, closes)]
    hi = smma(highs, 34); lo = smma(lows, 34); mi = zlema(src, 34)
    md = [(mi[i] - hi[i]) if mi[i] > hi[i] else (mi[i] - lo[i]) if mi[i] < lo[i] else 0.0 for i in range(n)]
    sb = sma(md, 9); sh = [md[i] - sb[i] for i in range(n)]
    i = n - 2
    side = "long" if src[i] > mi[i] else ("short" if src[i] < mi[i] else None)
    return side, {"imacd_src": src[i], "imacd_mi": mi[i], "imacd_md": md[i], "imacd_sb": sb[i], "imacd_sh": sh[i],
                  "imacd_side": ("BUY" if side == "long" else "SELL" if side == "short" else "No Trade")}

def combo_signal_s2(candles: List[dict]) -> Tuple[Optional[str], Dict[str, float]]:
    closes = [c["c"] for c in candles]; highs = [c["h"] for c in candles]; lows = [c["l"] for c in candles]
    tsa_sig, tsa_info = compute_tsa(closes)
    im_sig,  im_info  = imacd(highs, lows, closes)
    comb = "long" if (tsa_sig == "long" and im_sig == "long") else ("short" if (tsa_sig == "short" and im_sig == "short") else None)
    info = {**tsa_info, **im_info, "s2_combined": ("LONG" if comb == "long" else "SHORT" if comb == "short" else "-")}
    return comb, info

def strong_s2(candles: List[dict]) -> Optional[str]:
    closes = [c["c"] for c in candles]; highs = [c["h"] for c in candles]; lows = [c["l"] for c in candles]
    tsa_sig, _ = compute_tsa(closes)
    _, s = imacd(highs, lows, closes)
    if not s: return None
    md = s.get("imacd_md", 0.0); sb = s.get("imacd_sb", 0.0)
    if tsa_sig == "long" and md > abs(sb): return "long"
    if tsa_sig == "short" and md < -abs(sb): return "short"
    return None

# ====== TSL (Continuous / Step-wise) ======
class TrailingStop:
    """
    mode='continuous':
      LONG : anchor=max(anchor, price);  stop=anchor*(1-pct); hit if price <= stop
      SHORT: anchor=min(anchor, price);  stop=anchor*(1+pct); hit if price >= stop
    mode='step':
      LONG : if price >= anchor*(1+pct): anchor=price; stop=anchor*(1-pct)
             hit if price <= stop
      SHORT: if price <= anchor*(1-pct): anchor=price; stop=anchor*(1+pct)
             hit if price >= stop
    """
    def __init__(self, side: str, entry_px: float, pct: float, mode: str):
        self.side = side
        self.entry = float(entry_px)
        self.pct = float(pct)
        self.mode = mode  # 'continuous' or 'step'
        self.anchor = float(entry_px)
        self.stop = self._calc_stop(self.anchor)

    def _calc_stop(self, anchor: float) -> float:
        return anchor*(1.0 - self.pct) if self.side == "long" else anchor*(1.0 + self.pct)

    def reset_if_entry_changed(self, entry_px: float):
        if self.entry <= 0: return
        if abs(entry_px - self.entry) / self.entry > 0.001:
            self.entry = float(entry_px)
            self.anchor = float(entry_px)
            self.stop = self._calc_stop(self.anchor)

    def update_and_check(self, price: float) -> bool:
        if math.isnan(price) or price <= 0: return False
        if self.mode == "continuous":
            if self.side == "long":
                if price > self.anchor:
                    self.anchor = price
                    self.stop = self._calc_stop(self.anchor)
                return price <= self.stop
            else:
                if price < self.anchor:
                    self.anchor = price
                    self.stop = self._calc_stop(self.anchor)
                return price >= self.stop
        else:  # step-wise
            if self.side == "long":
                if price >= self.anchor*(1.0 + self.pct):
                    self.anchor = price
                    self.stop = self._calc_stop(self.anchor)
                return price <= self.stop
            else:
                if price <= self.anchor*(1.0 - self.pct):
                    self.anchor = price
                    self.stop = self._calc_stop(self.anchor)
                return price >= self.stop

class TslManager:
    def __init__(self, pct: float, mode: str):
        self.pct = float(pct)
        self.mode = mode
        self.track: Dict[str, TrailingStop] = {}

    def _key(self, pair: str, side: str) -> str:
        return f"{pair}:{side}"

    def ensure(self, pair: str, side: str, entry_px: float) -> TrailingStop:
        k = self._key(pair, side)
        t = self.track.get(k)
        if t is None:
            t = TrailingStop(side, entry_px, self.pct, self.mode)
            self.track[k] = t
        else:
            t.mode = self.mode  # keep in sync if user toggled between runs
            t.reset_if_entry_changed(entry_px)
        return t

    def get_stop_px(self, pair: str, side: str) -> float:
        t = self.track.get(self._key(pair, side))
        return t.stop if t else float("nan")

    def update_and_hit(self, pair: str, side: str, price: float) -> bool:
        t = self.track.get(self._key(pair, side))
        return t.update_and_check(price) if t else False

    def clear(self, pair: str, side: str):
        self.track.pop(self._key(pair, side), None)

# ====== Trade executor (selected pair) ======
class TradeExecutor:
    def __init__(self, paper: bool, pair: str, margin_amt: float, leverage: int,
                 q_inc: float, min_qty: float, max_long: int, max_short: int):
        self.paper = paper
        self.pair = pair
        self.margin_amt = margin_amt
        self.leverage = leverage
        self.q_inc = q_inc
        self.min_qty = min_qty
        self.max_long = int(max_long)
        self.max_short = int(max_short)
        self.current_pos = None  # {"side": "long"/"short", "qty": float, "entry_px": float, "opened_ms": int}
        self.last_close_ms = 0
        self.paper_log: List[dict] = []

        # --- Paper wallet / margin ledger ---
        # Currency follows MARGIN_MODE (INR or USDT)
        if self.paper:
            self.paper_margin_initial = float(margin_amt)     # user’s original input (target to "recover" to)
            self.paper_margin_current = float(margin_amt)     # used for sizing; falls on losses, recovers with profits
            self.paper_wallet_balance = float(margin_amt)     # simulated wallet balance
            self.paper_last_pnl_ccy = 0.0                     # last realized PnL in MARGIN currency
        else:
            # not used in real mode
            self.paper_margin_initial = 0.0
            self.paper_margin_current = 0.0
            self.paper_wallet_balance = 0.0
            self.paper_last_pnl_ccy = 0.0

    def compute_qty(self, price_usdt: float, fx_inr: float,
                    margin_amt_override: Optional[float] = None,
                    leverage_override: Optional[int] = None) -> float:
        margin_amt = float(self.margin_amt if margin_amt_override is None else margin_amt_override)
        lev = int(self.leverage if leverage_override is None else leverage_override)
        if lev < 1: lev = 1
        if MARGIN_MODE == "INR":
            qty_raw = qty_from_margin_in_inr(margin_amt * MARGIN_SAFETY, lev, price_usdt, fx_inr)
        else:
            denom = price_usdt if is_posfinite(price_usdt) else 1.0
            qty_raw = (margin_amt * MARGIN_SAFETY * lev) / max(denom, 1e-12)
        return snap_qty(qty_raw, self.q_inc, self.min_qty)

    def open_position(self, side: str, price_usdt: float, fx_inr: float) -> Tuple[bool, str]:
        if self.current_pos is not None:
            return False, "Skipped: already in position"
        if not is_posfinite(price_usdt):
            return False, "Failed: entry price not available"

        # qty computed using the *current* (user) leverage
        qty = self.compute_qty(price_usdt, fx_inr)
        if qty <= 0:
            return False, f"Failed: computed qty <= 0 (min_qty={self.min_qty}, step={self.q_inc})"

        # PAPER: just open (no retry needed)
        if self.paper:
            self.current_pos = {"side": side, "qty": qty, "entry_px": price_usdt, "opened_ms": _now_ms()}
            self.paper_log.append({"type":"open", "side": side, "qty": qty, "px": price_usdt, "ts": _now_ms(), "lev": self.leverage})
            print(f"[PAPER] OPEN {side.upper()} {qty} {self.pair} @ {price_usdt:.2f} (lev {self.leverage}x)")
            return True, f"{side.upper()} executed (paper) @ {price_usdt:.4f}, qty {qty:.6f}"

        # REAL: try user-defined leverage first
        try:
            # ensure we have a fresh authoritative price right before sizing/placing the real order
            try:
                fresh_px = last_price_usdt(self.pair, prefer_mark_for_valuation=True, force_refresh=True)
                if is_posfinite(fresh_px):
                    price_usdt = fresh_px
                    qty = self.compute_qty(price_usdt, fx_inr)
            except Exception:
                pass

            resp = create_futures_market_order(self.pair, "buy" if side=="long" else "sell", qty, self.leverage)
            self.current_pos = {"side": side, "qty": qty, "entry_px": price_usdt, "opened_ms": _now_ms()}
            print(f"[REAL] OPEN {side.upper()} {qty} {self.pair} @ ~{price_usdt:.2f} (lev {self.leverage}x)")
            print("[order_create]", json.dumps(resp, indent=2))
            return True, f"{side.upper()} executed (real) ~@ {price_usdt:.4f}, qty {qty:.6f}"
        except Exception as e:
            # Retry with API max leverage for the direction
            fb_lev = self.max_long if side == "long" else self.max_short
            # Only retry if different from the user leverage
            if fb_lev != self.leverage:
                try:
                    resp2 = create_futures_market_order(self.pair, "buy" if side=="long" else "sell", qty, fb_lev)
                    # reflect the actually-used lev for UI
                    self.leverage = fb_lev
                    self.current_pos = {"side": side, "qty": qty, "entry_px": price_usdt, "opened_ms": _now_ms()}
                    print(f"[REAL][FALLBACK] OPEN {side.upper()} {qty} {self.pair} @ ~{price_usdt:.2f} (lev {fb_lev}x)")
                    print("[order_create_fallback]", json.dumps(resp2, indent=2))
                    return True, f"{side.upper()} executed with API max lev ({fb_lev}x) ~@ {price_usdt:.4f}, qty {qty:.6f}"
                except Exception as e2:
                    msg2 = getattr(e2, "response", None)
                    reason2 = (msg2.text if getattr(msg2, "text", None) else str(e2))
                    print("[order_create_fallback] error:", reason2)
                    return False, f"Failed (fallback): {reason2}"

            # No different max lev available or retry not applicable
            msg = getattr(e, "response", None)
            reason = (msg.text if getattr(msg, "text", None) else str(e))
            print("[order_create] error:", reason)
            return False, f"Failed: {reason}"


    def close_position(self, price_usdt: float, fx_inr: float) -> Tuple[bool, str]:
        if self.current_pos is None:
            return False, "Skipped: no position to close"
        side = self.current_pos["side"]; qty = self.current_pos["qty"]; opp = "sell" if side=="long" else "buy"

        # ===== PAPER: realize PnL into wallet, adjust margin rules =====
        if self.paper:
            entry_px = self.current_pos["entry_px"]
            pnl_usdt = (price_usdt - entry_px) * qty if side == "long" else (entry_px - price_usdt) * qty
            pnl_ccy = pnl_usdt * fx_inr if MARGIN_MODE == "INR" else pnl_usdt
            self.paper_last_pnl_ccy = float(pnl_ccy)
            # wallet always += PnL
            self.paper_wallet_balance += pnl_ccy
            # margin falls with losses; recovers toward initial using profits (but does NOT exceed initial)
            if pnl_ccy < 0:
                self.paper_margin_current = max(0.0, self.paper_margin_current + pnl_ccy)
            else:
                if self.paper_margin_current < self.paper_margin_initial:
                    recover = min(pnl_ccy, self.paper_margin_initial - self.paper_margin_current)
                    self.paper_margin_current += recover
            self.paper_log.append({"type":"close", "side": side, "qty": qty, "px": price_usdt,
                                   "ts": _now_ms(), "pnl_ccy": pnl_ccy,
                                   "paper_margin_after": self.paper_margin_current,
                                   "wallet_after": self.paper_wallet_balance})
            self.current_pos = None; self.last_close_ms = _now_ms()
            sign = "+" if pnl_ccy >= 0 else "-"
            return True, (f"Closed {side.upper()} (paper) @ {price_usdt:.4f} | PnL {sign}{abs(pnl_ccy):.2f} {MARGIN_MODE} | "
                          f"Wallet {self.paper_wallet_balance:.2f} • Margin {self.paper_margin_current:.2f}")

        # ===== REAL: just place market opposite =====
        try:
            # refresh price used for logging/valuation when closing for real
            try:
                fresh_px = last_price_usdt(self.pair, prefer_mark_for_valuation=True, force_refresh=True)
                if is_posfinite(fresh_px):
                    price_usdt = fresh_px
            except Exception:
                pass

            resp = create_futures_market_order(self.pair, opp, qty, self.leverage)
            self.current_pos = None; self.last_close_ms = _now_ms()
            return True, f"Closed {side.upper()} (real) ~@ {price_usdt:.4f}"
        except Exception as e:
            msg = getattr(e, "response", None)
            reason = (msg.text if getattr(msg, "text", None) else str(e))
            return False, f"Failed to close: {reason}"

    def sync_from_open_row_if_needed(self, open_rows_for_pair: List[Dict[str, Any]]):
        if self.current_pos is not None: return
        for r in open_rows_for_pair:
            if r.get("pair") == self.pair:
                side = r.get("side"); entry_px = try_float(r.get("entry_px")); qty = try_float(r.get("qty"))
                if side in ("long","short") and entry_px > 0 and qty > 0:
                    self.current_pos = {"side": side, "qty": qty, "entry_px": entry_px, "opened_ms": _now_ms()}
                    print(f"[sync] Adopted existing {side.upper()} {self.pair} @ {entry_px:.6f} for TSL.")
                    return

# ===== Pair selection with Top Picks + Load More (bordered grid, 5 columns) =====
TOP_PICKS = [
    "B-BTC_USDT","B-ETH_USDT","B-XRP_USDT","B-SOL_USDT","B-BNB_USDT",
    "B-BCH_USDT","B-SUI_USDT","B-LINK_USDT","B-AVAX_USDT","B-AAVE_USDT",
    "B-DOGE_USDT","B-MAGIC_USDT","B-FARTCOIN_USDT","B-TRUMP_USDT","B-MELANIA_USDT",
]

def _print_bordered_grid(items, title="Symbols", cols=5, cell_emoji="📈"):
    """
    Render items as a bordered grid (cols columns), numbered for selection.
    """
    if not items:
        print(f"\n{title}\n(none)")
        return

    print(f"\n{title}  📜\n")

    # Build labels
    labels = [f"{i+1:>3}. {sym}  {cell_emoji}" for i, sym in enumerate(items)]

    # Layout (row-major)
    rows = (len(labels) + cols - 1) // cols
    grid = [["" for _ in range(cols)] for _ in range(rows)]
    for idx, lab in enumerate(labels):
        r = idx // cols
        c = idx % cols
        grid[r][c] = lab

    # Column widths
    col_w = [0]*cols
    for c in range(cols):
        col_w[c] = max((len(grid[r][c]) for r in range(rows)), default=0)

    # Helper to draw a separator line
    def sep(ch="-"):
        return "+" + "+".join((ch*(w+2)) for w in col_w) + "+"

    # Print rows
    print(sep("-"))
    for r in range(rows):
        cells = []
        for c in range(cols):
            s = grid[r][c]
            cells.append(" " + s.ljust(col_w[c]) + " ")
        print("|" + "|".join(cells) + "|")
        print(sep("-"))

def select_pair_with_top_picks(active_pairs: list) -> str:
    # Keep the specified order but only those that are actually active
    filtered_top = [s for s in TOP_PICKS if s in active_pairs]

    # If no top picks are active, jump straight to ALL symbols
    if not filtered_top:
        all_syms = sorted(active_pairs)
        _print_bordered_grid(all_syms, title="All Active Symbols  🔎", cols=5)
        while True:
            sel = input("Pick a symbol by NUMBER or paste the SYMBOL: ").strip()
            if sel.isdigit():
                n = int(sel)
                if 1 <= n <= len(all_syms):
                    return all_syms[n-1]
            if sel in all_syms:
                return sel
            print("❌ Invalid selection. Try again.")
    else:
        # Show Top Picks first
        _print_bordered_grid(filtered_top, title="⭐  Top Picks (USDT)  🚀", cols=5)
        print("  0. 🔽  Load more (show all symbols)\n")
        while True:
            sel = input(f"Choose 1..{len(filtered_top)} or 0 to Load more: ").strip().lower()
            if sel == "0":
                all_syms = sorted(active_pairs)
                _print_bordered_grid(all_syms, title="All Active Symbols  🔎", cols=5)
                while True:
                    s2 = input("Pick a symbol by NUMBER or paste the SYMBOL: ").strip()
                    if s2.isdigit():
                        n = int(s2)
                        if 1 <= n <= len(all_syms):
                            return all_syms[n-1]
                    if s2 in all_syms:
                        return s2
                    print("❌ Invalid selection. Try again.")
            elif sel.isdigit():
                n = int(sel)
                if 1 <= n <= len(filtered_top):
                    return filtered_top[n-1]
            print("❌ Invalid selection. Try again.")

# ====== Signal activity, S/R, and Trend strength ======

def donchian_levels(candles: List[dict], lookback: int) -> Tuple[float, float]:
    """Return (hi, lo) of last 'lookback' completed candles."""
    n = len(candles)
    if n < lookback + 2:
        return float("nan"), float("nan")
    # use completed candles only: exclude the very last forming one if you append live mins
    block = candles[-(lookback+1):-1]
    hi = max(c["h"] for c in block)
    lo = min(c["l"] for c in block)
    return hi, lo

def is_signal_active_s1(side: str, last_c: dict, live_px: float) -> bool:
    if not is_posfinite(live_px):
        return False
    if side == "long":
        return (live_px >= last_c["ema9"]
                and last_c["ema9"] > last_c["ema21"]
                and last_c["lips"] > last_c["teeth"] > last_c["jaw"])
    else:
        return (live_px <= last_c["ema9"]
                and last_c["ema9"] < last_c["ema21"]
                and last_c["lips"] < last_c["teeth"] < last_c["jaw"])

def trend_strength_s1(side: str, last_c: dict, prev_c: dict) -> bool:
    ema_spread = abs(last_c["ema9"] - last_c["ema21"]) / max(1e-12, last_c["ema21"])
    ema_slope  = last_c["ema9"] - prev_c["ema9"]
    if side == "long":
        return (ema_spread >= TREND_EMA_SPREAD_MIN) and (last_c["rsi14"] >= TREND_RSI_LONG_MIN) and (ema_slope > 0)
    else:
        return (ema_spread >= TREND_EMA_SPREAD_MIN) and (last_c["rsi14"] <= TREND_RSI_SHORT_MAX) and (ema_slope < 0)

def is_signal_active_s2(side: str, s2_info: Dict[str, float]) -> bool:
    if not s2_info: return False
    src = s2_info.get("imacd_src"); mi = s2_info.get("imacd_mi")
    if src is None or mi is None or not (is_posfinite(src) and is_posfinite(mi)): return False
    return (src > mi) if side == "long" else (src < mi)

def trend_strength_s2(side: str, s2_info: Dict[str, float]) -> bool:
    if not s2_info: return False
    md = s2_info.get("imacd_md", 0.0); sb = abs(s2_info.get("imacd_sb", 0.0))
    ratio = abs(md) / max(sb, 1e-9)
    if side == "long":
        return (md > 0) and (ratio >= TREND_S2_MD_SB_RATIO_MIN)
    else:
        return (md < 0) and (ratio >= TREND_S2_MD_SB_RATIO_MIN)

def near_support_or_resistance(side: str, live_px: float, dc_hi: float, dc_lo: float) -> Tuple[bool, str]:
    """
    True => 'too close to S/R' (block entry), unless it's a breakout through the level by a tiny buffer.
    For LONG: avoid if too close to Donchian high (resistance).
    For SHORT: avoid if too close to Donchian low (support).
    """
    if not is_posfinite(live_px) or not is_posfinite(dc_hi) or not is_posfinite(dc_lo):
        return True, "invalid S/R or price"
    # tiny breakout buffers so true breakouts are not blocked
    breakout_up_buf = 1.0002
    breakout_dn_buf = 0.9998
    if side == "long":
        # if we’re already breaking out above Donchian high (by a hair), allow
        if live_px >= dc_hi * breakout_up_buf:
            return False, ""
        dist_to_res = (dc_hi - live_px) / max(live_px, 1e-9)
        if dist_to_res <= ENTRY_SR_NEAR_PCT:
            return True, f"near resistance ({dist_to_res*100:.2f}%)"
        return False, ""
    else:
        if live_px <= dc_lo * breakout_dn_buf:
            return False, ""
        dist_to_sup = (live_px - dc_lo) / max(live_px, 1e-9)
        if dist_to_sup <= ENTRY_SR_NEAR_PCT:
            return True, f"near support ({dist_to_sup*100:.2f}%)"
        return False, ""

def validate_entry(strategy: str,
                   side: str,
                   candles: List[dict],
                   last_c: Optional[dict],
                   live_px: float,
                   s2_or_s3_info: Dict[str, float]) -> Tuple[bool, str]:
    """
    Returns (ok_to_trade, reason).
    - S1 & S2: same as before (S/R + strong trend checks).
    - S3: no S/R check; require signal still active & not choppy (handled in signal fn); skip strength.
    """
    if last_c is None or len(candles) < (DONCHIAN_LOOKBACK + 3):
        # For S3 we don't need Donchian, but keep a modest history check to be safe.
        if strategy == "s3":
            if last_c is None or len(candles) < 25:
                return False, "insufficient history"
        else:
            return False, "insufficient history"

    if strategy == "s1":
        prev_c = candles[-3]
        dc_hi, dc_lo = donchian_levels(candles, DONCHIAN_LOOKBACK)
        active = is_signal_active_s1(side, last_c, live_px)
        if not active:
            return False, "signal not active on live"
        near_sr, why_sr = near_support_or_resistance(side, live_px, dc_hi, dc_lo)
        strong = trend_strength_s1(side, last_c, prev_c)
        if strong and not near_sr:
            return True, "valid & strong"
        reasons = []
        if near_sr: reasons.append(why_sr or "near S/R")
        if not strong: reasons.append("weak trend")
        return False, " / ".join(reasons) if reasons else "not strong"

    if strategy == "s2":
        prev_c = candles[-3]
        dc_hi, dc_lo = donchian_levels(candles, DONCHIAN_LOOKBACK)
        active = is_signal_active_s2(side, s2_or_s3_info)
        if not active:
            return False, "signal not active on live"
        near_sr, why_sr = near_support_or_resistance(side, live_px, dc_hi, dc_lo)
        strong = trend_strength_s2(side, s2_or_s3_info)
        if strong and not near_sr:
            return True, "valid & strong"
        reasons = []
        if near_sr: reasons.append(why_sr or "near S/R")
        if not strong: reasons.append("weak trend")
        return False, " / ".join(reasons) if reasons else "not strong"

    # strategy == "s3"
    active = is_signal_active_s3(side, last_c, live_px)
    if not active:
        return False, "signal not active on live"
    # chop was already filtered inside signal_strategy3; if we ever pass a flag, honor it:
    if s2_or_s3_info and s2_or_s3_info.get("s3_chop") == "yes":
        return False, "no-trade zone (chop)"
    return True, "valid"

# ====== MAIN LOOP ======
def main():
    if not API_KEY or not API_SECRET:
        raise SystemExit("Set COINDCX_API_KEY and COINDCX_API_SECRET in your .env")

    print(f"CoinDCX Futures • {time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime())}  |  Mode={MARGIN_MODE}")

    # ===== Account type (Real / Paper) =====
    acc_choice = ask_choice("Select account type:", {"1": "Real", "2": "Paper Trade"}, default_key="2")
    PAPER = (acc_choice == "2")

    # ===== Pair selection (Top Picks → Load More → 5-col bordered grid) =====
    try:
        pairs = active_instruments(MARGIN_MODE)
        if not pairs:
            print("[pairs] No active instruments for", MARGIN_MODE)
            sys.exit(1)
        TRADING_PAIR = select_pair_with_top_picks(pairs)
        print(f"\n✅ Selected pair:  {TRADING_PAIR}   🧩\n")
    except Exception as e:
        print("[pairs] error:", e)
        sys.exit(1)

    # ===== Timeframe selection =====
    tf_choice = ask_choice(
        "Select candlestick timeframe:",
        {"1":"1m","2":"5m","3":"15m","4":"30m","5":"1h","6":"2h","7":"4h","8":"8h"},
        default_key="1"
    )
    TF_LABEL = {"1":"1m","2":"5m","3":"15m","4":"30m","5":"1h","6":"2h","7":"4h","8":"8h"}[tf_choice]
    CONFIRM_TF_LABEL = NEXT_HIGHER_TF[TF_LABEL]  # may be None for 8h

    # ===== Instrument detail (sizing limits) =====
    try:
        det = instrument_detail(TRADING_PAIR, MARGIN_MODE)
    except Exception as e:
        print("[instrument] error:", e)
        det = {}
    q_inc = float(det.get("quantity_increment", 1)) if det else 1.0
    min_qty = float(det.get("min_quantity") or det.get("min_trade_size") or q_inc) if det else q_inc
    max_long = int(det.get("max_leverage_long", 30) or 30)
    max_short = int(det.get("max_leverage_short", max_long) or max_long)
    max_lev = max(max_long, max_short)

    print(f"\nSelected pair: {TRADING_PAIR}")
    print(f"Timeframe={TF_LABEL}, Min qty={min_qty}, step={q_inc}, Max leverage long={max_long}x, short={max_short}x")

    # ===== Margin + leverage =====
    if MARGIN_MODE == "INR":
        while True:
            try:
                margin_amt = float(input("Enter margin AMOUNT (INR): ").strip())
                break
            except Exception:
                print("Please enter a number.")
    else:
        while True:
            try:
                margin_amt = float(input("Enter margin AMOUNT (USDT): ").strip())
                break
            except Exception:
                print("Please enter a number.")

    while True:
        try:
            lev = int(input(f"Enter leverage (1..{max_lev}): ").strip() or str(min(30, max_lev)))
            lev = max(1, min(lev, max_lev))
            break
        except Exception:
            print("Enter an integer leverage.")

    # ===== Strategy picker (S1 / S2 / S3) =====
    strat_choice = ask_choice(
        "Select strategy:",
        {"1": "Strategy 1 — EMA/RSI + Alligator",
        "2": "Strategy 2 — TSA + iMACD",
        "3": "Strategy 3 — MA Cross (9/21)"},
        default_key="2"
    )
    STRATEGY = "s1" if strat_choice == "1" else ("s2" if strat_choice == "2" else "s3")

    # ===== TSL mode & % =====
    tsl_mode_choice = ask_choice(
        "Select TSL mode:",
        {"1": "Continuous (tick-by-tick)", "2": "Step-wise (% steps)"},
        default_key="1"
    )
    TSL_MODE = "continuous" if tsl_mode_choice == "1" else "step"

    while True:
        try:
            tsl_percent_input = float(input("Set TSL % (e.g., 1.0 = 1%): ").strip())
            if tsl_percent_input <= 0:
                print("TSL % must be > 0.")
                continue
            TSL_PCT = tsl_percent_input / 100.0
            break
        except Exception:
            print("Please enter a number (e.g., 1.0).")

    # ===== History & indicators bootstrap (base TF + optional confirm TF) =====
    base_boot_bars = max(200, HIST_MINUTES // TIMEFRAME_MINUTES[TF_LABEL])
    candles: List[dict] = []
    try:
        candles = fetch_candles_tf(TRADING_PAIR, TF_LABEL, base_boot_bars)
        # rebuild indicators for selected strategy
        if STRATEGY == "s1":
            build_indicators_s1(candles)
        elif STRATEGY == "s3":
            build_indicators_s3(candles)
        else:
            # S2 does not need EMA/RSI/Alligator here
            pass
    except Exception as e:
        print("[history] error:", e)

    candles_confirm: List[dict] = []
    if CONFIRM_TF_LABEL:
        try:
            conf_boot_bars = max(120, (HIST_MINUTES // TIMEFRAME_MINUTES[CONFIRM_TF_LABEL]))
            candles_confirm = fetch_candles_tf(TRADING_PAIR, CONFIRM_TF_LABEL, conf_boot_bars)
            if STRATEGY == "s1":
                build_indicators_s1(candles_confirm)
            # S2: no rebuild needed; S3: we skip HTF confirm entirely

        except Exception as e:
            print("[history-htf] error:", e)

    # ===== Init executor & TSL =====
    executor = TradeExecutor(PAPER, TRADING_PAIR, margin_amt, lev, q_inc, min_qty, max_long, max_short)
    tsl_mgr = TslManager(TSL_PCT, TSL_MODE)

    # Track non-selected external positions we adopt for TSL-only management
    external_positions: Dict[Tuple[str, str], Dict[str, float]] = {}

    # UI / status vars
    last_print = 0
    last_exec_msg = "-"   # surfaced in strategy table
    s2_info: Dict[str, float] = {}

    # ===== Main loop =====
    while True:
        try:
            fx_inr = usdt_inr_fx()

            # --- Price engine: refresh recent windows & rebuild indicators ---
            candles = refresh_candles_dedupe(TRADING_PAIR, TF_LABEL, candles, recent_bars=120)
            if STRATEGY == "s1":
                build_indicators_s1(candles)
            elif STRATEGY == "s3":
                build_indicators_s3(candles)
            else:
                pass  # S2 no rebuild needed

            if CONFIRM_TF_LABEL:
                candles_confirm = refresh_candles_dedupe(TRADING_PAIR, CONFIRM_TF_LABEL, candles_confirm, recent_bars=60)
                if STRATEGY == "s1":
                    build_indicators_s1(candles_confirm)
                # S2: none; S3: no HTF confirm


            # --- Signals on last completed candle (base TF) ---
            # Use mark price for valuation when available
            live_px_selected = last_price_usdt(TRADING_PAIR, prefer_mark_for_valuation=True)
            last_c = candles[-2] if len(candles) >= 2 else None

            normal_sig = strong_sig = None
            s2_info = {}
            s3_info = {}
            if last_c:
                if STRATEGY == "s1":
                    normal_sig = signal_strategy1(last_c)
                    strong_sig = strong_s1(last_c)
                elif STRATEGY == "s2":
                    normal_sig, s2_info = combo_signal_s2(candles)
                    strong_sig = strong_s2(candles)
                else:  # s3
                    normal_sig, s3_info = signal_strategy3(candles)
                    strong_sig = "-"   # not used for S3

            # --- Higher timeframe confirmation (direction must match) ---
            confirm_ok = True
            if CONFIRM_TF_LABEL and normal_sig in ("long","short"):
                if STRATEGY == "s1":
                    ht_c = candles_confirm[-2] if len(candles_confirm) >= 2 else None
                    ht_sig = signal_strategy1(ht_c) if ht_c else None
                    confirm_ok = (ht_sig == normal_sig)
                elif STRATEGY == "s2":
                    ht_sig, _ = combo_signal_s2(candles_confirm) if candles_confirm else (None, {})
                    confirm_ok = (ht_sig == normal_sig)
                else:  # S3 — no HTF confirm
                    confirm_ok = True


            # --- Fetch orders; derive OPEN/CLOSED (for ALL symbols) ---
            try:
                all_orders_raw = fetch_all_orders()
            except Exception:
                all_orders_raw = []
            all_orders_norm = [normalize_order(o) for o in (all_orders_raw or [])]
            all_orders_norm.sort(key=lambda x: _to_ms(x.get("created_at_raw") or 0), reverse=True)
            open_rows, closed_rows_last15 = derive_from_trades(all_orders_norm, fx_inr)

            # --- Adopt selected pair if needed (TSL management) ---
            executor.sync_from_open_row_if_needed([r for r in open_rows if r.get("pair") == TRADING_PAIR])

            # --- Adopt/refresh EXTERNAL (non-selected) positions (TSL-only; no re-entry) ---
            current_external = {}
            for r in open_rows:
                pair = r.get("pair"); side = r.get("side")
                if pair and side in ("long", "short") and pair != TRADING_PAIR:
                    entry_px = try_float(r.get("entry_px")); qty = try_float(r.get("qty"))
                    if entry_px > 0 and qty > 0:
                        key = (pair, side)
                        current_external[key] = {"qty": qty, "entry_px": entry_px}
                        tsl_mgr.ensure(pair, side, entry_px)
                        if key not in external_positions:
                            external_positions[key] = {"qty": qty, "entry_px": entry_px}
                            print(f"[adopt] Monitoring external {pair} {side.upper()} qty={qty:.6f} entry={entry_px:.6f}")
                        else:
                            if abs(external_positions[key]["entry_px"] - entry_px) / max(entry_px, 1e-9) > 0.001:
                                external_positions[key]["entry_px"] = entry_px

            for key in list(external_positions.keys()):
                if key not in current_external:
                    print(f"[adopt] External {key[0]} {key[1].upper()} no longer open; stopping monitoring.")
                    tsl_mgr.clear(key[0], key[1])
                    external_positions.pop(key, None)

            # ===== Entry/Exit Logic (Selected Pair) =====
            # 1) TSL-based exit on base TF only
            if executor.current_pos is not None:
                pos_side = executor.current_pos["side"]
                tsl_mgr.ensure(TRADING_PAIR, pos_side, executor.current_pos["entry_px"])
                if tsl_mgr.update_and_hit(TRADING_PAIR, pos_side, live_px_selected):
                    stop_px = tsl_mgr.get_stop_px(TRADING_PAIR, pos_side)
                    print(f"[TSL] Hit {TRADING_PAIR} {pos_side.upper()} at {live_px_selected:.6f} (stop {stop_px:.6f})")
                    ok, msg = executor.close_position(live_px_selected, fx_inr)
                    last_exec_msg = f"TSL close: {msg}"
                    tsl_mgr.clear(TRADING_PAIR, pos_side)

            # 2) Entry when flat — normal OR strong signal, validated + HTF confirm
            actionable = strong_sig if strong_sig in ("long", "short") else normal_sig
            if executor.current_pos is None and actionable in ("long", "short"):
                px_fallbacks = [
                    live_px_selected,
                    (candles[-1]["c"] if candles else float("nan")),
                    (candles[-2]["c"] if len(candles) >= 2 else float("nan")),
                ]
                entry_px = next((p for p in px_fallbacks if is_posfinite(p)), float("nan"))
                if not is_posfinite(entry_px):
                    last_exec_msg = "Failed: no valid entry price"
                else:
                    ok_val, why_val = validate_entry(
                        STRATEGY, actionable, candles, last_c, entry_px,
                        s2_info if STRATEGY == "s2" else (s3_info if STRATEGY == "s3" else {})
                    )

                    if not ok_val:
                        last_exec_msg = f"Skipped: {why_val}"
                    elif not confirm_ok:
                        last_exec_msg = f"Skipped: HTF ({CONFIRM_TF_LABEL}) disagrees"
                    else:
                        try_qty = executor.compute_qty(entry_px, fx_inr)
                        print(f"[entry] TF={TF_LABEL} actionable={actionable} entry_px={entry_px:.6f} try_qty={try_qty:.6f}")
                        ok, msg = executor.open_position(actionable, entry_px, fx_inr)
                        last_exec_msg = (f"{'LONG' if actionable=='long' else 'SHORT'} executed" if ok else f"{msg}")
                        if ok:
                            tsl_mgr.ensure(TRADING_PAIR, actionable, executor.current_pos["entry_px"])

            # 3) Flip on opposite normal signal — validate + HTF confirm
            elif executor.current_pos is not None and normal_sig in ("long", "short"):
                pos_side = executor.current_pos["side"]
                if (pos_side == "long" and normal_sig == "short") or (pos_side == "short" and normal_sig == "long"):
                    close_px = live_px_selected if is_posfinite(live_px_selected) else (candles[-1]["c"] if candles else 1.0)
                    okc, msgc = executor.close_position(close_px, fx_inr)
                    last_exec_msg = f"Close for flip: {msgc}"
                    tsl_mgr.clear(TRADING_PAIR, pos_side)

                    px_fallbacks = [
                        live_px_selected,
                        (candles[-1]["c"] if candles else float("nan")),
                        (candles[-2]["c"] if len(candles) >= 2 else float("nan")),
                    ]
            
                    entry_px = next((p for p in px_fallbacks if is_posfinite(p)), float("nan"))
                    if is_posfinite(entry_px):
                        ok_val, why_val = validate_entry(
                            STRATEGY, normal_sig, candles, last_c, entry_px,
                            s2_info if STRATEGY == "s2" else (s3_info if STRATEGY == "s3" else {})
                        )

                        # recompute HTF confirm for the new direction
                        ht_ok = True
                        if CONFIRM_TF_LABEL and normal_sig in ("long","short"):
                            if STRATEGY == "s1":
                                ht_c = candles_confirm[-2] if len(candles_confirm) >= 2 else None
                                ht_sig = signal_strategy1(ht_c) if ht_c else None
                                ht_ok = (ht_sig == normal_sig)
                            elif STRATEGY == "s2":
                                ht_sig, _ = combo_signal_s2(candles_confirm) if candles_confirm else (None, {})
                                ht_ok = (ht_sig == normal_sig)
                            else:  # S3 — no HTF confirm
                                ht_ok = True

                        if not ok_val:
                            last_exec_msg = f"Skipped flip: {why_val}"
                        elif not ht_ok:
                            last_exec_msg = f"Skipped flip: HTF ({CONFIRM_TF_LABEL}) disagrees"
                        else:
                            try_qty = executor.compute_qty(entry_px, fx_inr)
                            print(f"[flip] TF={TF_LABEL} new={normal_sig} entry_px={entry_px:.6f} try_qty={try_qty:.6f}")
                            ok, msg = executor.open_position(normal_sig, entry_px, fx_inr)
                            last_exec_msg = (f"{'LONG' if normal_sig=='long' else 'SHORT'} executed" if ok else f"{msg}")
                            if ok:
                                tsl_mgr.ensure(TRADING_PAIR, normal_sig, executor.current_pos["entry_px"])
                    else:
                        last_exec_msg = "Failed: no valid entry price for flip"

            # ===== External positions: TSL close only, no re-entry =====
            unique_external_pairs = sorted({pair for (pair, _) in external_positions.keys()})
            live_px_map: Dict[str, float] = {TRADING_PAIR: live_px_selected}
            for p in unique_external_pairs:
                if p not in live_px_map:
                    live_px_map[p] = last_price_usdt(p, prefer_mark_for_valuation=True)

            def close_external_position(pair: str, side: str, qty: float, price_usdt: float):
                opp = "sell" if side == "long" else "buy"
                if PAPER:
                    print(f"[PAPER][EXT] CLOSE {pair} {side.upper()} {qty:.6f} @ {price_usdt:.6f}")
                else:
                    try:
                        resp = create_futures_market_order(pair, opp, qty, 1)
                        print(f"[REAL][EXT] CLOSE {pair} {side.upper()} {qty:.6f} @ ~{price_usdt:.6f}")
                        print("[order_close_ext]", json.dumps(resp, indent=2))
                    except Exception as e:
                        print(f"[order_close_ext] error for {pair}: {e}")

            for (pair, side), meta in list(external_positions.items()):
                live_px = live_px_map.get(pair, float("nan"))
                if not is_posfinite(live_px):
                    continue
                if tsl_mgr.update_and_hit(pair, side, live_px):
                    stop_px = tsl_mgr.get_stop_px(pair, side)
                    print(f"[TSL][EXT] Hit {pair} {side.upper()} at {live_px:.6f} (stop {stop_px:.6f})")
                    close_external_position(pair, side, meta["qty"], live_px)
                    tsl_mgr.clear(pair, side)
                    external_positions.pop((pair, side), None)

            # ===== Paper parity: mirror selected OPEN row =====
            if executor.paper and executor.current_pos is not None:
                side = executor.current_pos["side"]
                qty = executor.current_pos["qty"]
                entry_px = executor.current_pos["entry_px"]
                mark_px = live_px_selected if is_posfinite(live_px_selected) else (candles[-1]["c"] if candles else entry_px)
                pnl_usdt = (mark_px - entry_px) * qty if side == "long" else (entry_px - mark_px) * qty
                open_rows = [r for r in open_rows if r.get("pair") != TRADING_PAIR]
                open_rows.append({
                    "id": "paper",
                    "pair": TRADING_PAIR,
                    "side": side,
                    "qty": f"{qty:.6f}",
                    "entry_px": f"{entry_px:.6f}",
                    "mark_px": f"{mark_px:.6f}",
                    "lev": f"{executor.leverage}x",
                    "pnl_open_inr": f"{(pnl_usdt * fx_inr):.2f} INR",
                    "entry_at": ms_to_utc(executor.current_pos.get("opened_ms")),
                    "updated_at": ms_to_utc(_now_ms()),
                })

            # ===== Inject Live Px & TSL Px into OPEN rows =====
            for r in open_rows:
                pair = r.get("pair")
                # live px (use cached map when available; otherwise fetch)
                if pair:
                    lp = live_px_map.get(pair) if 'live_px_map' in locals() else float('nan')
                    if not is_posfinite(lp):
                        lp = last_price_usdt(pair, prefer_mark_for_valuation=True)
                        if 'live_px_map' in locals():
                            live_px_map[pair] = lp
                    r["live_px"] = f"{lp:.6f}" if is_posfinite(lp) else "-"
                else:
                    r["live_px"] = "-"

                # TSL px
                side = r.get("side")
                if pair and side in ("long", "short"):
                    t = tsl_mgr.ensure(pair, side, try_float(r.get("entry_px")))
                    r["tsl_px"] = f"{t.stop:.6f}"
                else:
                    r["tsl_px"] = "-"


            # ===== Throttled printout / CSV =====
            now = time.time()
            if now - last_print >= POLL_SEC:
                os.system("cls" if os.name == "nt" else "clear")
                print(
                    f"CoinDCX Futures • {time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime())}"
                    f"  |  Mode={MARGIN_MODE} | {('PAPER' if PAPER else 'REAL')}"
                    f" • Pair={TRADING_PAIR} • Lev={executor.leverage}x • TSL={tsl_percent_input:.3f}% [{TSL_MODE}]"
                    f" • Strategy={'S1' if STRATEGY=='s1' else ('S2' if STRATEGY=='s2' else 'S3')}"
                )

                # Wallets quick view
                # Wallets quick view — REAL vs PAPER
                if not PAPER:
                    try:
                        w = futures_wallets()
                        def pick(js, sym):
                            items = []
                            if isinstance(js, list):
                                items = js
                            elif isinstance(js, dict):
                                for k in ("wallets", "data", "balances"):
                                    if isinstance(js.get(k), list):
                                        items = js[k]; break
                            for it in items:
                                s = (it.get("currency_short_name") or it.get("currency") or it.get("asset") or "").upper()
                                if s == sym:
                                    free = float(it.get("free_balance") or it.get("available_balance") or it.get("balance") or 0.0)
                                    locked = float(it.get("locked_balance") or it.get("locked") or 0.0)
                                    return free, locked
                            return 0.0, 0.0
                        free_inr, locked_inr = pick(w, "INR")
                        free_usdt, locked_usdt = pick(w, "USDT")
                        print(f"[wallets] INR free={free_inr:.2f} locked={locked_inr:.2f} | USDT free={free_usdt:.4f} locked={locked_usdt:.4f}")
                    except Exception as e:
                        print("[wallets] error:", e)
                else:
                    # PAPER summary line + detailed table
                    print(f"[paper] {MARGIN_MODE} wallet={executor.paper_wallet_balance:.2f} | "
                        f"trade margin={executor.paper_margin_current:.2f} | "
                        f"last_pnl={executor.paper_last_pnl_ccy:+.2f}")

                    _print_bordered_table(
                        "Paper — Wallet & Margin  💼",
                        [{
                            "ccy": MARGIN_MODE,
                            "allotted": f"{executor.paper_margin_initial:.2f}",
                            "trade_margin": f"{executor.paper_margin_current:.2f}",
                            "wallet": f"{executor.paper_wallet_balance:.2f}",
                            "last_pnl": f"{executor.paper_last_pnl_ccy:+.2f}",
                            "updated": ms_to_utc(_now_ms()),
                        }],
                        [
                            ("CCY", "ccy"),
                            ("Allotted Margin", "allotted"),
                            ("Trade Margin (current)", "trade_margin"),
                            ("Wallet Balance", "wallet"),
                            ("Last PnL", "last_pnl"),
                            ("Updated", "updated"),
                        ]
                    )


                # Pending orders
                try:
                    pending = fetch_orders_paginated("initial,open,partially_filled,untriggered", max_pages=1)
                except Exception:
                    pending = []
                pending_rows = [normalize_order(o) for o in (pending or [])]

                # OPEN table
                _print_bordered_table(
                    "Positions — OPEN (derived) + Paper + Adopted (TSL-enabled)",
                    open_rows,
                    [
                        ("ID", "id"), ("Pair", "pair"), ("Side", "side"), ("Qty", "qty"), ("Live Px", "live_px"),
                        ("Entry Px", "entry_px"), ("Mark Px", "mark_px"), ("TSL Px", "tsl_px"), ("Lev", "lev"),
                        ("PnL (open) INR", "pnl_open_inr"),
                        ("Entry UTC", "entry_at"), ("Updated", "updated_at"),
                    ]

                )

                # PENDING table
                _print_bordered_table(
                    "Orders — PENDING/OPEN",
                    pending_rows,
                    [
                        ("ID", "id"), ("Pair", "pair"), ("Side", "side"), ("Status", "status"),
                        ("Qty", "qty"), ("AvgPx", "avg_price"), ("Lev", "lev"),
                        ("Created", "created_at"), ("Updated", "updated_at"),
                    ]
                )

                # CLOSED table
                # _print_bordered_table(
                #     "Positions — CLOSED (from fills) — last 15",
                #     closed_rows_last15,
                #     [
                #         ("ID (open->close)", "id"), ("Pair", "pair"), ("Side", "side"), ("Qty", "qty"),
                #         ("Entry Px", "entry_px"), ("Exit Px", "exit_px"), ("Lev", "lev"),
                #         ("PnL (realized) INR", "pnl_inr"),
                #         ("Entry UTC", "entry_at"), ("Exit UTC", "exit_at"),
                #     ]
                # )

                # Strategy / Indicators table (selected pair)
                if STRATEGY == "s1":
                    row = {}
                    if last_c:
                        row = {
                            "time": ms_to_utc(last_c["ts"]),
                            "ema9": f"{last_c['ema9']:.4f}",
                            "ema21": f"{last_c['ema21']:.4f}",
                            "rsi14": f"{last_c['rsi14']:.2f}",
                            "lips": f"{last_c['lips']:.4f}",
                            "teeth": f"{last_c['teeth']:.4f}",
                            "jaw": f"{last_c['jaw']:.4f}",
                            "signal": normal_sig or "-",
                            "strong": strong_sig or "-",
                            "live_px": f"{(live_px_selected if is_posfinite(live_px_selected) else (candles[-1]['c'] if candles else float('nan'))):.6f}",
                            "pos": (executor.current_pos['side'] if executor.current_pos else "-"),
                            "tsl_px": (f"{tsl_mgr.get_stop_px(TRADING_PAIR, executor.current_pos['side']):.6f}" if executor.current_pos else "-"),
                            "exec": last_exec_msg or "-",
                        }
                    _print_bordered_table(
                        f"Strategy — Indicators & Signal (S1: EMA/RSI + Alligator)  • TF={TF_LABEL}" +
                        (f"  • Confirm TF={CONFIRM_TF_LABEL}" if CONFIRM_TF_LABEL else ""),
                        [row] if row else [],
                        [
                            ("Candle Time (UTC)", "time"), ("EMA9", "ema9"), ("EMA21", "ema21"), ("RSI14", "rsi14"),
                            ("Lips", "lips"), ("Teeth", "teeth"), ("Jaw", "jaw"),
                            ("Signal", "signal"), ("Strong", "strong"), ("Live Px", "live_px"),
                            ("Position", "pos"), ("TSL Px", "tsl_px"), ("Exec Status", "exec"),
                        ]
                    )
                elif STRATEGY == "s3":
                    row = {}
                    if last_c:
                        live_disp = live_px_selected if is_posfinite(live_px_selected) else (candles[-1]['c'] if candles else float("nan"))
                        row = {
                            "time": ms_to_utc(last_c["ts"]),
                            "sma9": f"{last_c.get('sma_s', float('nan')):.4f}",
                            "sma21": f"{last_c.get('sma_l', float('nan')):.4f}",
                            "cross": s3_info.get("s3_cross", "-"),
                            "unt_hi": s3_info.get("s3_untouched_hi", "-"),
                            "unt_lo": s3_info.get("s3_untouched_lo", "-"),
                            "break": s3_info.get("s3_break", "-"),
                            "chop":  s3_info.get("s3_chop", "-"),
                            "signal": normal_sig or "-",
                            "strong": "-",  # not used in S3
                            "live_px": f"{live_disp:.6f}" if is_posfinite(live_disp) else "-",
                            "pos": (executor.current_pos['side'] if executor.current_pos else "-"),
                            "tsl_px": (f"{tsl_mgr.get_stop_px(TRADING_PAIR, executor.current_pos['side']):.6f}" if executor.current_pos else "-"),
                            "exec": last_exec_msg or "-",
                        }
                    _print_bordered_table(
                        "Strategy — Indicators & Signal (S3: MA Cross 9/21)",
                        [row] if row else [],
                        [
                            ("Candle Time (UTC)", "time"),
                            ("SMA9", "sma9"), ("SMA21", "sma21"),
                            ("Cross", "cross"), ("Untouched Hi", "unt_hi"), ("Untouched Lo", "unt_lo"),
                            ("Break Lvl", "break"), ("Chop?", "chop"),
                            ("Signal", "signal"), ("Strong", "strong"), ("Live Px", "live_px"),
                            ("Position", "pos"), ("TSL Px", "tsl_px"), ("Exec Status", "exec"),
                        ]
                    )

                else:
                    row = {}
                    if last_c:
                        live_disp = live_px_selected if is_posfinite(live_px_selected) else (candles[-1]['c'] if candles else float("nan"))
                        row = {
                            "time": ms_to_utc(last_c["ts"]),
                            "tsa_dyn_ema": f"{s2_info.get('tsa_dyn_ema', float('nan')):.4f}" if s2_info else "-",
                            "tsa_wma2": f"{s2_info.get('tsa_wma2', float('nan')):.4f}" if s2_info else "-",
                            "im_src": f"{s2_info.get('imacd_src', float('nan')):.4f}" if s2_info else "-",
                            "im_mi": f"{s2_info.get('imacd_mi', float('nan')):.4f}" if s2_info else "-",
                            "im_md": f"{s2_info.get('imacd_md', float('nan')):.4f}" if s2_info else "-",
                            "im_sb": f"{s2_info.get('imacd_sb', float('nan')):.4f}" if s2_info else "-",
                            "im_sh": f"{s2_info.get('imacd_sh', float('nan')):.4f}" if s2_info else "-",
                            "combined": s2_info.get("s2_combined", "-") if s2_info else "-",
                            "signal": normal_sig or "-",
                            "strong": strong_sig or "-",
                            "live_px": f"{live_disp:.6f}" if is_posfinite(live_disp) else "-",
                            "pos": (executor.current_pos['side'] if executor.current_pos else "-"),
                            "tsl_px": (f"{tsl_mgr.get_stop_px(TRADING_PAIR, executor.current_pos['side']):.6f}" if executor.current_pos else "-"),
                            "exec": last_exec_msg or "-",
                        }
                    _print_bordered_table(
                        f"Strategy — Indicators & Signal (S2: TSA + iMACD)  • TF={TF_LABEL}" +
                        (f"  • Confirm TF={CONFIRM_TF_LABEL}" if CONFIRM_TF_LABEL else ""),
                        [row] if row else [],
                        [
                            ("Candle Time (UTC)", "time"),
                            ("TSA dynEMA", "tsa_dyn_ema"), ("TSA WMA2", "tsa_wma2"),
                            ("iMACD src", "im_src"), ("iMACD MI", "im_mi"),
                            ("iMACD MD", "im_md"), ("iMACD SB", "im_sb"), ("iMACD SH", "im_sh"),
                            ("S2 Combined", "combined"),
                            ("Signal", "signal"), ("Strong", "strong"), ("Live Px", "live_px"),
                            ("Position", "pos"), ("TSL Px", "tsl_px"), ("Exec Status", "exec"),
                        ]
                    )

                # CSV export of all normalized orders
                trades_csv_columns = [
                    ("ID", "id"), ("Pair", "pair"), ("Side", "side"), ("Status", "status"),
                    ("Qty", "qty"), ("Filled", "filled"), ("AvgPx", "avg_price"), ("Lev", "lev"),
                    ("Created", "created_at"), ("Updated", "updated_at"),
                    ("CreatedRaw", "created_at_raw"), ("UpdatedRaw", "updated_at_raw"),
                ]
                export_csv(TRADES_CSV_PATH, all_orders_norm, trades_csv_columns)

                # Recent paper activity (last 5)
                if executor.paper and executor.paper_log:
                    print("\nPaper log (most recent 5):")
                    for rowp in executor.paper_log[-5:]:
                        print(rowp)

                last_print = now

            time.sleep(POLL_SEC)

        except KeyboardInterrupt:
            print("\nStopping… Bye.")
            break
        except Exception as e:
            print("[loop] error:", e)
            time.sleep(POLL_SEC)

if __name__ == "__main__":
    main()
    
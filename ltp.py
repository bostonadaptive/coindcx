import os
import time
import requests
import json
from typing import Any, Dict, Optional
import logging
import hmac
import hashlib

# Try to reuse existing helpers if available (optional)
try:
    from global_cache import get as gc_get
except Exception:
    gc_get = None
try:
    from mcp_client import mcp_get
except Exception:
    mcp_get = None

# Base URLs - mirror the other modules' behaviour and allow env overrides
_mcp_base = os.environ.get('COINDCX_MCP') or os.environ.get('COINDCX_PROXY')
API_BASE = os.environ.get('COINDCX_API_BASE') or _mcp_base or "https://api.coindcx.com"
PUBLIC_BASE = os.environ.get('COINDCX_PUBLIC_BASE') or _mcp_base or "https://public.coindcx.com"

session = requests.Session()
session.headers.update({"Content-Type": "application/json"})

# in-memory cache for quick LTPs
_LTP_CACHE: Dict[str, Dict[str, Any]] = {}

# Optional Redis integration (shared cross-process cache)
REDIS_URL = os.environ.get('REDIS_URL') or os.environ.get('REDIS_URI')
_redis = None
if REDIS_URL:
    try:
        import redis as _redislib
        _redis = _redislib.from_url(REDIS_URL, decode_responses=True)
    except Exception:
        _redis = None

# lightweight module logger
logger = logging.getLogger("ltp")
if not logger.handlers:
    # default to INFO level; app can reconfigure
    h = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] ltp: %(message)s")
    h.setFormatter(fmt)
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

def _parse_numeric_from(obj: Any, keys: list) -> Optional[float]:
    if obj is None:
        return None
    if isinstance(obj, (int, float)):
        return float(obj)
    if isinstance(obj, str):
        try:
            return float(obj)
        except Exception:
            return None
    if isinstance(obj, dict):
        for k in keys:
            if k in obj and obj[k] not in (None, ""):
                try:
                    return float(obj[k])
                except Exception:
                    try:
                        return float(str(obj[k]))
                    except Exception:
                        return None
        # try nested data array/object
        if 'data' in obj:
            data = obj['data']
            if isinstance(data, dict):
                return _parse_numeric_from(data, keys)
            if isinstance(data, list) and data:
                return _parse_numeric_from(data[0], keys)
    return None


def _redis_key(sym: str) -> str:
    return f"ltp:{sym}"


# Signing helper (avoid importing app to prevent circular imports)
COINDCX_API_KEY = os.environ.get('COINDCX_API_KEY') or os.environ.get('API_KEY')
COINDCX_SECRET = (os.environ.get('COINDCX_API_SECRET') or os.environ.get('COINDCX_API_SECRET') or os.environ.get('SECRET_KEY') or '')

# Prefer futures/derivatives websocket LTP entries over spot when set to truthy
COINDCX_PREFER_FUTURES = os.environ.get('COINDCX_PREFER_FUTURES', '').lower() in ('1', 'true', 'yes')
# Hard preference: if true, always return futures/derivatives websocket LTP when available
COINDCX_FORCE_FUTURES = os.environ.get('COINDCX_FORCE_FUTURES', '').lower() in ('1', 'true', 'yes')
# Which margin modes should force futures when COINDCX_FORCE_FUTURES is enabled.
# Comma-separated, e.g. 'USDT,INR'. Default to 'USDT' for derivatives valuation unless overridden.
_force_margin_modes_raw = os.environ.get('COINDCX_FORCE_FUTURES_MARGIN', os.environ.get('COINDCX_FORCE_FUTURES_FOR_MARGIN', 'USDT'))
try:
    COINDCX_FORCE_FUTURES_MARGIN = set([s.strip().upper() for s in _force_margin_modes_raw.split(',') if s.strip()])
except Exception:
    COINDCX_FORCE_FUTURES_MARGIN = {'USDT'}

def _signed_post(path: str, body: dict, timeout: int = 8) -> Optional[Any]:
    """POST to API_BASE + path with HMAC-SHA256 signature header, return JSON or None on error."""
    try:
        if not COINDCX_API_KEY or not COINDCX_SECRET:
            return None
        payload = json.dumps(body, separators=(",", ":"))
        sig = hmac.new(COINDCX_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        headers = {"Content-Type": "application/json", "X-AUTH-APIKEY": COINDCX_API_KEY, "X-AUTH-SIGNATURE": sig}
        r = session.post(API_BASE + path, data=payload, headers=headers, timeout=timeout)
        # Debug: optionally print signed request/response to help diagnose parity
        try:
            if os.environ.get('LTP_DEBUG_PRINT', '').lower() in ('1', 'true', 'yes'):
                try:
                    print(f"SIGNED POST -> {API_BASE + path} payload={payload} headers={{'X-AUTH-APIKEY': '***', 'X-AUTH-SIGNATURE': sig}} response_status={r.status_code}")
                    try:
                        print('SIGNED POST response:', r.text)
                    except Exception:
                        pass
                except Exception:
                    pass
        except Exception:
            pass
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            # If response isn't JSON, return raw text for debugging purposes
            try:
                return r.text
            except Exception:
                return None
    except Exception:
        return None


def _signed_get(path: str, body: dict, timeout: int = 8) -> Optional[Any]:
    """Signed GET to API_BASE + path with HMAC-SHA256 signature header. Some API
    routes return a list for GET (e.g. full ticker list). Returns parsed JSON or
    raw text on parse failure, or None on error."""
    try:
        if not COINDCX_API_KEY or not COINDCX_SECRET:
            return None
        payload = json.dumps(body, separators=(",", ":"))
        sig = hmac.new(COINDCX_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        headers = {"Content-Type": "application/json", "X-AUTH-APIKEY": COINDCX_API_KEY, "X-AUTH-SIGNATURE": sig}
        r = session.get(API_BASE + path, data=payload, headers=headers, timeout=timeout)
        try:
            if os.environ.get('LTP_DEBUG_PRINT', '').lower() in ('1', 'true', 'yes'):
                try:
                    print(f"SIGNED GET -> {API_BASE + path} payload={payload} headers={{'X-AUTH-APIKEY':'***','X-AUTH-SIGNATURE':sig}} response_status={r.status_code}")
                    try:
                        print('SIGNED GET response:', r.text[:1000])
                    except Exception:
                        pass
                except Exception:
                    pass
        except Exception:
            pass
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            try:
                return r.text
            except Exception:
                return None
    except Exception:
        return None


def _get_cache_entry(sym: str) -> Optional[Dict[str, Any]]:
    """Return cache entry (dict) from Redis if available, otherwise in-memory cache."""
    try:
        if _redis:
            v = _redis.get(_redis_key(sym))
            if v:
                try:
                    return json.loads(v)
                except Exception:
                    return None
        # fallback to in-memory
        return _LTP_CACHE.get(sym)
    except Exception:
        return _LTP_CACHE.get(sym)


def _set_cache_entry(sym: str, data: Dict[str, Any], ttl: Optional[int] = None) -> None:
    """Store entry into Redis (if configured) and the in-memory cache.
    data should be JSON-serializable.
    """
    try:
        # shallow copy to avoid accidental mutation
        d = dict(data)
        _LTP_CACHE[sym] = d
        # optional debug print for live tick observation
        try:
            if os.environ.get('LTP_DEBUG_PRINT', '').lower() in ('1', 'true', 'yes'):
                try:
                    print(f"LTP cache update -> {sym}: {d.get('price')} (src={d.get('src')})")
                except Exception:
                    pass
        except Exception:
            pass
        if _redis:
            try:
                _redis.set(_redis_key(sym), json.dumps(d))
                if ttl:
                    _redis.expire(_redis_key(sym), int(ttl))
            except Exception:
                pass
    except Exception:
        pass


def get_ltp_cache_snapshot() -> Dict[str, Dict[str, Any]]:
    """Return a JSON-serializable snapshot of the current LTP cache.
    If Redis is configured, fetch keys with prefix 'ltp:' and merge with in-memory cache.
    """
    out: Dict[str, Dict[str, Any]] = {}
    try:
        if _redis:
            try:
                # Redis SCAN for keys matching prefix
                cursor = '0'
                while True:
                    cursor, keys = _redis.scan(cursor=cursor, match='ltp:*', count=100)
                    for k in keys:
                        try:
                            v = _redis.get(k)
                            if not v:
                                continue
                            key_name = k.split(':', 1)[1]
                            try:
                                out[key_name] = json.loads(v)
                            except Exception:
                                out[key_name] = {'raw': v}
                        except Exception:
                            continue
                    if cursor == '0' or cursor == 0:
                        break
            except Exception:
                # on redis failure, fall back to in-memory
                out.update({k: v for k, v in _LTP_CACHE.items()})
        else:
            out.update({k: v for k, v in _LTP_CACHE.items()})
    except Exception:
        out = {k: v for k, v in _LTP_CACHE.items()}
    return out

def instrument_detail(pair: str, margin_mode: str = 'USDT') -> dict:
    """Fetch instrument detail (returns dict) - defensive about caches/proxies."""
    # try global cache / mcp proxy first
    try:
        if gc_get:
            js = gc_get('/exchange/v1/derivatives/futures/data/instrument')
            if js:
                # cached endpoint may not respect params; try to find matching pair
                if isinstance(js, dict) and js.get('instrument'):
                    return js.get('instrument')
                if isinstance(js, list):
                    # list may contain many instruments - find matching
                    for it in js:
                        if isinstance(it, dict) and (it.get('market') == pair or it.get('pair') == pair):
                            return it
        if mcp_get:
            js = mcp_get('/exchange/v1/derivatives/futures/data/instrument', params={'pair': pair, 'margin_currency_short_name': margin_mode})
            if js:
                if isinstance(js, dict) and js.get('instrument'):
                    return js.get('instrument')
                if isinstance(js, dict) and isinstance(js.get('data'), list) and js.get('data'):
                    return js.get('data')[0]
    except Exception:
        pass

    # direct API fallback
    try:
        r = session.get(API_BASE + "/exchange/v1/derivatives/futures/data/instrument",
                        params={"pair": pair, "margin_currency_short_name": margin_mode}, timeout=8)
        r.raise_for_status()
        js = r.json()
        if isinstance(js, dict):
            if isinstance(js.get('instrument'), dict):
                return js.get('instrument')
            if isinstance(js.get('data'), list) and js.get('data'):
                return js.get('data')[0]
    except Exception:
        pass
    return {}

def last_price_usdt(pair: str, *, ttl: float = 2.0, prefer_mark_for_valuation: bool = True, force_refresh: bool = False, margin_mode: str = 'USDT') -> float:
    """Robust LTP retrieval used across the app.

    Strategy:
    1) Try instrument detail (signed/proxied) - prefer mark_price for valuation
    2) Try public /market_data/last_price
    3) Try public /market_data/ticker
    4) Fallback to candlesticks last close
    Uses in-memory TTL cache to reduce load.
    """
    now = time.time()
    key = pair.upper()
    cached = _get_cache_entry(key)
    # If we have a recent cached value, we normally return it to avoid extra requests.
    # However, if configured to prefer futures, check for websocket-sourced futures entries
    # before returning the cached spot value.
    if not force_refresh and cached and (now - cached.get('ts', 0.0) <= ttl):
        # local helper to build normalized candidate keys (mirrors later _normalize)
        def _candidate_keys_top(pair_in: str):
            p = (pair_in or '').upper()
            if p.startswith('B-'):
                market_b = p
            else:
                if '_' in p:
                    body = p.replace('-', '').replace('/', '')
                    if not body.startswith('B-') and not body.startswith('B'):
                        if body.startswith('B'):
                            market_b = 'B-' + body[1:]
                        else:
                            market_b = 'B-' + body
                    else:
                        market_b = body
                else:
                    if p.endswith('USDT'):
                        base = p[:-4]; quote = 'USDT'
                    else:
                        base = p[:-3]; quote = p[-3:]
                    market_b = f'B-{base}_{quote}'
            raw = market_b[2:].replace('_','') if market_b.startswith('B-') else market_b.replace('_','')
            return [pair_in.upper(), market_b, raw, raw.replace('_', ''), market_b.replace('B-', ''), pair_in.upper().replace('B-', '')]

        # Hard force: if configured and the requested margin_mode is in the configured set,
        # return any websocket-sourced derivatives/futures entry immediately
        if COINDCX_FORCE_FUTURES and (str(margin_mode or '').upper() in COINDCX_FORCE_FUTURES_MARGIN):
            try:
                for c in _candidate_keys_top(pair):
                    try:
                        entry = _get_cache_entry(c)
                        if not entry or not isinstance(entry, dict):
                            continue
                        src = str(entry.get('src') or '').lower()
                        if src.startswith('ws') and ('deriv' in src or 'future' in src or 'futures' in src or 'derivatives' in src):
                            try:
                                return float(entry.get('price'))
                            except Exception:
                                return float('nan')
                    except Exception:
                        continue
            except Exception:
                pass

        # Soft preference: check futures entries if configured
        if COINDCX_PREFER_FUTURES:
            try:
                for c in _candidate_keys_top(pair):
                    try:
                        entry = _get_cache_entry(c)
                        if not entry or not isinstance(entry, dict):
                            continue
                        src = str(entry.get('src') or '').lower()
                        if src.startswith('ws') and ('deriv' in src or 'future' in src or 'futures' in src or 'derivatives' in src):
                            try:
                                return float(entry.get('price'))
                            except Exception:
                                return float('nan')
                    except Exception:
                        continue
            except Exception:
                pass

        # No preferred futures found (or not configured) -> return cached
        return float(cached.get('price', float('nan')))

    # normalize pair into common representations used by CoinDCX
    def _normalize(pair_in: str):
        p = (pair_in or '').upper()
        # If already B- prefix with underscore, keep
        if p.startswith('B-'):
            market_b = p
        else:
            # if contains underscore already like ETH_USDT or B-ETH_USDT
            if '_' in p:
                body = p.replace('-', '').replace('/', '')
                if not body.startswith('B-') and not body.startswith('B'):
                    # ensure B- prefix
                    if body.startswith('B'):
                        market_b = 'B-' + body[1:]
                    else:
                        market_b = 'B-' + body
                else:
                    market_b = body
            else:
                # assume formats like ETHUSDT or ETHINR
                if p.endswith('USDT'):
                    base = p[:-4]; quote = 'USDT'
                else:
                    base = p[:-3]; quote = p[-3:]
                market_b = f'B-{base}_{quote}'
        # flatten market without B- for some endpoints
        raw = market_b[2:].replace('_','') if market_b.startswith('B-') else market_b.replace('_','')
        return market_b, raw

    market_b, raw_sym = _normalize(pair)

    # Prefer very recent websocket-sourced entries (written by the LTP aggregator)
    try:
        live_window = max(1.5, float(ttl)) if ttl else 2.0
    except Exception:
        live_window = 2.0
    candidate_keys = [key, market_b, raw_sym, raw_sym.replace('_', ''), market_b.replace('B-', ''), key.replace('B-', '')]
    # If forced preference is enabled and the margin_mode matches, return any websocket-sourced derivatives/futures entry immediately
    if COINDCX_FORCE_FUTURES and (str(margin_mode or '').upper() in COINDCX_FORCE_FUTURES_MARGIN):
        try:
            for c in candidate_keys:
                try:
                    entry = _get_cache_entry(c)
                    if not entry or not isinstance(entry, dict):
                        continue
                    src = str(entry.get('src') or '').lower()
                    if src.startswith('ws') and ('deriv' in src or 'future' in src or 'futures' in src or 'derivatives' in src):
                        try:
                            return float(entry.get('price'))
                        except Exception:
                            return float('nan')
                except Exception:
                    continue
        except Exception:
            pass

    # If configured to prefer futures (soft), attempt to return any websocket-sourced derivatives/futures entry first
    if COINDCX_PREFER_FUTURES:
        try:
            for c in candidate_keys:
                try:
                    entry = _get_cache_entry(c)
                    if not entry or not isinstance(entry, dict):
                        continue
                    src = str(entry.get('src') or '').lower()
                    # look for websocket-derived derivatives/futures indicators in src
                    if src.startswith('ws') and ('deriv' in src or 'future' in src or 'futures' in src or 'derivatives' in src):
                        try:
                            return float(entry.get('price'))
                        except Exception:
                            return float('nan')
                except Exception:
                    continue
        except Exception:
            pass

    for c in candidate_keys:
        try:
            entry = _get_cache_entry(c)
            if not entry or not isinstance(entry, dict):
                continue
            src = str(entry.get('src') or '')
            # aggregator writes src like 'ws_currentPrices' or 'ws_price_change'
            if src.startswith('ws'):
                rec_ts = entry.get('ts', 0)
                try:
                    rec_ts_f = float(rec_ts)
                except Exception:
                    rec_ts_f = 0.0
                # support ms or seconds timestamps
                if rec_ts_f > 1e11:
                    rec_ts_f = rec_ts_f / 1000.0
                if time.time() - rec_ts_f <= live_window:
                    try:
                        return float(entry.get('price'))
                    except Exception:
                        return float('nan')
        except Exception:
            continue

    # 0) Try CoinDCX exchange ticker (legacy/fast) for the normalized market id
    # 0a) If we have server-side API credentials, prefer a signed /exchange/ticker call (authoritative)
    try:
        js_signed = _signed_post('/exchange/ticker', {'market': market_b}, timeout=5)
        if isinstance(js_signed, dict):
            p = _parse_numeric_from(js_signed, ['ltp','last_price','price','last'])
            if p is not None:
                _set_cache_entry(raw_sym, {'ts': now, 'price': float(p), 'src': 'signed_exchange_ticker'})
                _set_cache_entry(market_b, {'ts': now, 'price': float(p), 'src': 'signed_exchange_ticker'})
                logger.info(f"price for {pair} from signed_exchange_ticker: {p}")
                return float(p)
        # If signed POST returned None or not_found, some API installations return
        # a signed GET which yields a list of tickers. Try that and find our market.
        if js_signed in (None, ''):
            js_get = _signed_get('/exchange/ticker', {'market': market_b}, timeout=6)
            if isinstance(js_get, list):
                # find matching market entry
                for it in js_get:
                    if not isinstance(it, dict):
                        continue
                    # match by market key or by sanitized market_b
                    if str(it.get('market') or '').upper() in (market_b.upper(), raw_sym.upper(), market_b.upper().replace('_','')):
                        p = _parse_numeric_from(it, ['last_price','ltp','price','last'])
                        if p is not None:
                            _set_cache_entry(raw_sym, {'ts': now, 'price': float(p), 'src': 'signed_exchange_ticker'})
                            _set_cache_entry(market_b, {'ts': now, 'price': float(p), 'src': 'signed_exchange_ticker'})
                            logger.info(f"price for {pair} from signed_exchange_ticker(get-list): {p}")
                            return float(p)
    except Exception as e:
        logger.debug(f"signed_exchange_ticker error for {pair}: {e}")

    # 0b) Try CoinDCX exchange ticker (legacy/fast) for the normalized market id (unsigned)
    try:
        # prefer API_BASE exchange ticker endpoint (POST) which commonly returns {'ltp': ...}
        r = session.post(API_BASE + '/exchange/ticker', json={'market': market_b}, timeout=6)
        if r.ok:
            js = r.json()
            # prefer ltp or last_price keys
            p = _parse_numeric_from(js, ['ltp','last_price','price','last'])
            if p is not None:
                _set_cache_entry(raw_sym, {'ts': now, 'price': float(p), 'src': 'exchange_ticker'})
                _set_cache_entry(market_b, {'ts': now, 'price': float(p), 'src': 'exchange_ticker'})
                logger.info(f"price for {pair} from exchange_ticker: {p}")
                return float(p)
    except Exception as e:
        logger.debug(f"exchange_ticker error for {pair}: {e}")

    # 1) instrument detail
    try:
        det = instrument_detail(pair, margin_mode)
        if isinstance(det, dict) and det:
            candidates = (['mark_price','last_price','index_price'] if prefer_mark_for_valuation else ['last_price','mark_price','index_price'])
            p = _parse_numeric_from(det, candidates)
            if p is not None:
                _set_cache_entry(key, {'ts': now, 'price': float(p), 'src': 'instrument_detail'})
                logger.info(f"price for {pair} from instrument_detail (prefer_mark={prefer_mark_for_valuation}): {p}")
                return float(p)
    except Exception as e:
        logger.debug(f"instrument_detail error for {pair}: {e}")

    # 2) public last_price
    try:
        r = session.get(PUBLIC_BASE + '/market_data/last_price', params={'pair': pair, 'pcode': 'f'}, timeout=6)
        r.raise_for_status()
        js = r.json()
        p = _parse_numeric_from(js, ['last_price','price','value'])
        if p is not None:
            _set_cache_entry(key, {'ts': now, 'price': float(p), 'src': 'public_last_price'})
            logger.info(f"price for {pair} from public_last_price: {p}")
            return float(p)
    except Exception as e:
        logger.debug(f"public_last_price error for {pair}: {e}")

    # 3) public ticker
    try:
        r = session.get(PUBLIC_BASE + '/market_data/ticker', params={'pair': pair, 'pcode': 'f'}, timeout=6)
        r.raise_for_status()
        js = r.json()
        p = _parse_numeric_from(js, ['last_price','price','last','ticker','l'])
        if p is not None:
            _set_cache_entry(key, {'ts': now, 'price': float(p), 'src': 'public_ticker'})
            logger.info(f"price for {pair} from public_ticker: {p}")
            return float(p)
    except Exception as e:
        logger.debug(f"public_ticker error for {pair}: {e}")

    # 4) fallback to candlesticks
    try:
        end_sec = int(time.time()); start_sec = end_sec - 8*60
        r = session.get(PUBLIC_BASE + '/market_data/candlesticks', params={'pair': pair, 'from': start_sec, 'to': end_sec, 'resolution': '1', 'pcode': 'f'}, timeout=8)
        r.raise_for_status()
        js = r.json() or {}
        rows = js.get('data') or []
        if rows:
            last = rows[-1]
            if isinstance(last, dict):
                for k in ('close','c'):
                    if k in last:
                        try:
                            p = float(last[k]);
                            _set_cache_entry(key, {'ts': now, 'price': float(p), 'src': 'candlestick_close'})
                            logger.info(f"price for {pair} from candlestick_close: {p}")
                            return float(p)
                        except Exception:
                            pass
    except Exception as e:
        logger.debug(f"candlesticks error for {pair}: {e}")

    # return cached stale if available
    if cached and 'price' in cached:
        logger.info(f"returning cached price for {pair}: {cached.get('price')} (src={cached.get('src')})")
        return float(cached['price'])
    return float('nan')

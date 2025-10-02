"""Compare signed /exchange/ticker vs websocket-cached LTPs continuously.

Usage:
  python scripts\compare_ltp_streams.py B-ETH_USDT 2

If COINDCX_API_KEY and COINDCX_API_SECRET are set, the script will call the signed
POST and compare the numeric price to current cache (from ltp.get_ltp_cache_snapshot()).
It prints JSON lines with the signed value, cached value(s), age, and diff.
"""
import sys
import time
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ltp import _signed_post, _signed_get, get_ltp_cache_snapshot

MARKET = sys.argv[1] if len(sys.argv) > 1 else 'B-ETH_USDT'
INTERVAL = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
LOG_FILE = sys.argv[3] if len(sys.argv) > 3 else None

print(f"Comparing signed /exchange/ticker for {MARKET} to websocket cache every {INTERVAL}s")
if LOG_FILE:
    print('Logging diffs to', LOG_FILE)

out_fh = None
if LOG_FILE:
    out_fh = open(LOG_FILE, 'a', encoding='utf-8')

try:
    while True:
        now = time.time()
        signed = None
        try:
            signed = _signed_post('/exchange/ticker', {'market': MARKET}, timeout=5)
        except Exception as e:
            signed = {'error': str(e)}
        # If POST returned no useful result, try signed GET list which some
        # deployments return as the canonical ticker payload
        if not signed:
            try:
                signed = _signed_get('/exchange/ticker', {'market': MARKET}, timeout=6)
            except Exception:
                pass

        try:
            snap = get_ltp_cache_snapshot() or {}
        except Exception:
            snap = {}

        # find relevant keys in cache
        keys = [MARKET.upper(), MARKET.upper().replace('B-',''), MARKET.upper().replace('_',''), MARKET.upper().replace('_','').replace('B-','')]
        cache_hits = {}
        for k in keys:
            if k in snap:
                cache_hits[k] = snap[k]

        # parse signed numeric if present
        signed_px = None
        signed_src = None
        if isinstance(signed, dict):
            for candidate in ('ltp','last_price','price','last'):
                if candidate in signed and signed[candidate] not in (None,''):
                    try:
                        signed_px = float(signed[candidate])
                        signed_src = candidate
                        break
                    except Exception:
                        pass
            # sometimes the API nests the payload under 'data'
            if signed_px is None and 'data' in signed and isinstance(signed['data'], dict):
                for candidate in ('ltp','last_price','price','last'):
                    if candidate in signed['data'] and signed['data'][candidate] not in (None,''):
                        try:
                            signed_px = float(signed['data'][candidate])
                            signed_src = 'data.' + candidate
                            break
                        except Exception:
                            pass
        # If signed returned a list (GET list), try to find our market entry
        if isinstance(signed, list):
            raw_candidate = MARKET.upper()
            # normalize common forms
            raw_candidate_alt = raw_candidate.replace('B-','').replace('_','')
            for it in signed:
                if not isinstance(it, dict):
                    continue
                m = str(it.get('market') or '').upper()
                if m in (raw_candidate, raw_candidate_alt, raw_candidate.replace('_','')):
                    for candidate in ('last_price','ltp','price','last'):
                        if candidate in it and it[candidate] not in (None,''):
                            try:
                                signed_px = float(it[candidate])
                                signed_src = 'list.' + candidate
                                signed = it
                                break
                            except Exception:
                                pass
                    if signed_px is not None:
                        break
        # build output object
        out = {'ts': now, 'market': MARKET, 'signed_raw': signed, 'signed_px': signed_px, 'signed_src': signed_src, 'cache_hits': {}}
        for k, v in cache_hits.items():
            try:
                price = v.get('price')
                ts = v.get('ts')
                # normalize ts
                try:
                    tsf = float(ts)
                    if tsf > 1e11:
                        tsf = tsf/1000.0
                except Exception:
                    tsf = 0.0
                age = round(now - tsf, 3) if tsf else None
                out['cache_hits'][k] = {'price': price, 'ts': tsf, 'age_s': age, 'src': v.get('src')}
            except Exception:
                out['cache_hits'][k] = {'raw': v}

        # compute diffs if both present
        if out['signed_px'] is not None:
            diffs = {}
            for k, v in out['cache_hits'].items():
                try:
                    if v.get('price') is not None:
                        diffs[k] = round(float(v.get('price')) - float(out['signed_px']), 6)
                except Exception:
                    diffs[k] = None
            out['diffs'] = diffs
        else:
            out['diffs'] = None

        line = json.dumps(out, default=str, ensure_ascii=False)
        print(line)
        if out_fh:
            out_fh.write(line + '\n')
            out_fh.flush()

        time.sleep(INTERVAL)

except KeyboardInterrupt:
    print('\nStopped by user')
finally:
    if out_fh:
        out_fh.close()

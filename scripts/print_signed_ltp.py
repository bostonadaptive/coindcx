"""Poll signed and unsigned /exchange/ticker for a market and print raw responses.

Usage:
  python scripts\print_signed_ltp.py B-ETH_USDT [interval_seconds]

If COINDCX_API_KEY and COINDCX_API_SECRET are set, the signed response will be attempted and
printed. Set LTP_DEBUG_PRINT=1 to get extra debug logs from the ltp module.
"""
import sys
import time
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ltp import _signed_post, session

MARKET = sys.argv[1] if len(sys.argv) > 1 else 'B-ETH_USDT'
INTERVAL = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0

print(f"Polling signed + unsigned /exchange/ticker for {MARKET} every {INTERVAL}s. Ctrl-C to stop.")

while True:
    try:
        now = time.time()
        signed = None
        try:
            signed = _signed_post('/exchange/ticker', {'market': MARKET}, timeout=5)
        except Exception as e:
            signed = f"_signed_post exception: {e}"

        try:
            r = session.post((os.environ.get('COINDCX_API_BASE') or 'https://api.coindcx.com') + '/exchange/ticker', json={'market': MARKET}, timeout=6)
            unsigned = None
            try:
                unsigned = r.json()
            except Exception:
                unsigned = r.text
        except Exception as e:
            unsigned = f"unsigned POST exception: {e}"

        out = {
            'ts': now,
            'market': MARKET,
            'signed': signed,
            'unsigned': unsigned
        }
        try:
            import json
            print(json.dumps(out, default=str, ensure_ascii=False))
        except Exception:
            print(out)

        time.sleep(INTERVAL)
    except KeyboardInterrupt:
        print('\nStopped by user.')
        break
    except Exception as e:
        print('Error in loop:', e)
        time.sleep(INTERVAL)

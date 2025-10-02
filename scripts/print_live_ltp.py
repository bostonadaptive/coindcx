"""Start the in-process LTP aggregator and continuously print LTP cache updates.

Usage: python scripts\print_live_ltp.py

Stops on Ctrl-C.
"""
import time
import json
import sys
import os
import traceback

# Ensure project root is on sys.path so imports like `import ltp` succeed when
# the script is executed from the `scripts/` directory.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Importing start functions may start background threads inside the app module
try:
    from app import start_ltp_aggregator, start_ltp_poller
except Exception:
    start_ltp_aggregator = None
    start_ltp_poller = None

from ltp import get_ltp_cache_snapshot

PRINT_FILTER = None  # e.g. 'ETH' or 'B-ETH' to limit output; None prints everything
POLL_INTERVAL = 1.0

if __name__ == '__main__':
    print('Starting live LTP printer. Ctrl-C to stop.')
    last_ts = {}
    try:
        if start_ltp_aggregator:
            try:
                print('Starting LTP aggregator...')
                start_ltp_aggregator()
            except Exception as e:
                print('start_ltp_aggregator() raised:', e)
        else:
            print('No start_ltp_aggregator available in app module.')

        # Optionally start poller as a fallback
        if start_ltp_poller:
            try:
                print('Starting LTP poller fallback (non-blocking).')
                start_ltp_poller()
            except Exception:
                # If poller already started or fails that's ok
                pass

        while True:
            snap = get_ltp_cache_snapshot() or {}
            now = time.time()
            keys = sorted(snap.keys())
            for k in keys:
                if PRINT_FILTER and PRINT_FILTER.upper() not in k.upper():
                    continue
                v = snap.get(k) or {}
                ts = v.get('ts')
                price = v.get('price')
                src = v.get('src')
                # normalize ts to seconds float
                try:
                    tsf = float(ts)
                    if tsf > 1e11:
                        tsf = tsf / 1000.0
                except Exception:
                    tsf = 0.0
                prev = last_ts.get(k)
                # print if new key or ts changed
                if prev != tsf:
                    last_ts[k] = tsf
                    out = {'key': k, 'price': price, 'src': src, 'ts': tsf, 'age_s': round(now - tsf, 3)}
                    try:
                        print(json.dumps(out, ensure_ascii=False))
                    except Exception:
                        print(out)
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print('\nStopped by user.')
    except Exception:
        traceback.print_exc()
        sys.exit(1)

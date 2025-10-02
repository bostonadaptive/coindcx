"""
Print future LTP for B-ETH_USDT continuously (or for a given duration).
Usage:
  python scripts/print_future_ltp.py         # run indefinitely
  python scripts/print_future_ltp.py --duration 10   # run for 10 seconds (demo)

The script forces futures preference for margin_mode USDT in-process so it uses futures LTPs.
"""
import os
import time
import argparse

# Force futures preference for this process (read before importing ltp)
os.environ.setdefault('COINDCX_FORCE_FUTURES', '1')
os.environ.setdefault('COINDCX_FORCE_FUTURES_MARGIN', 'USDT')

parser = argparse.ArgumentParser(description='Print futures LTP for B-ETH_USDT')
parser.add_argument('--pair', default='B-ETH_USDT', help='Market id to print (default B-ETH_USDT)')
parser.add_argument('--margin_mode', default='USDT', help='Margin mode to use for preference (default USDT)')
parser.add_argument('--interval', type=float, default=0.5, help='Seconds between polls')
parser.add_argument('--duration', type=float, default=None, help='Run duration in seconds (default: forever)')
args = parser.parse_args()

import sys
# ensure project root is on sys.path so local imports work when script is executed directly
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Import here so env vars are picked up by ltp module
try:
    import ltp
except Exception as e:
    print('Failed to import ltp module:', e)
    raise

pair = args.pair
margin_mode = args.margin_mode
interval = max(0.05, args.interval)
end_time = time.time() + args.duration if args.duration and args.duration > 0 else None

print(f"Printing futures LTP for {pair} (margin_mode={margin_mode}) every {interval}s. Press Ctrl-C to stop.")
try:
    while True:
        try:
            px = ltp.last_price_usdt(pair, ttl=1.0, force_refresh=False, margin_mode=margin_mode)
        except Exception as e:
            px = float('nan')
            print('error calling last_price_usdt ->', e)
        # also show raw cache entries for debugging
        cache_entry = ltp._get_cache_entry(pair)
        ts_ms = int(time.time() * 1000)
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{ts_ms}] {pair} -> {px}  cache_src={cache_entry.get('src') if isinstance(cache_entry, dict) else None}")
        if end_time and time.time() >= end_time:
            break
        time.sleep(interval)
except KeyboardInterrupt:
    print('\nStopped by user')

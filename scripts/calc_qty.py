"""Demo script: calculate qty from INR margin using the helper in app.py.

Example from user:
 margin = 5000 INR, leverage = 40, usd_inr_rate = 86, price = 4165
"""
import sys, os
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import compute_qty_from_inr_margin

if __name__ == '__main__':
    margin_inr = 5000
    leverage = 40
    usd_inr_rate = 86
    price = 4165
    res = compute_qty_from_inr_margin(margin_inr, leverage, price, usd_inr_rate)
    print('input: margin_inr=', margin_inr, 'leverage=', leverage, 'usd_inr_rate=', usd_inr_rate, 'price=', price)
    print('margin_usd =', res.get('margin_usd'))
    print('available_usd =', res.get('available_usd'))
    print('qty =', res.get('qty'))

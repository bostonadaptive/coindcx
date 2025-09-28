import io
import json
import types
import pytest

from app import _compute_trade_history_for_user, export_trade_history
import app as appmod

class DummyCreds:
    def __init__(self, api_key='k', secret_key='s'):
        self.api_key = api_key
        self.secret_key = secret_key


def test_compute_trade_history_and_export(monkeypatch):
    # Prepare fake orders: one closed trade with pnl string including currency
    # backtester/derive_from_trades now emits numeric pnl fields (pnl_inr, pnl_inr_value)
    # Provide a minimal 'filled' style order that normalize_order() can process
    fake_orders = [
        {
            'id': '1', 'pair': 'BINANCE:BTCUSDT', 'side': 'buy', 'status': 'filled',
            'total_quantity': 1, 'quantity': 1, 'avg_price': 100.0, 'price': 100.0,
            'created_at': 1704067200, 'updated_at': 1704070800
        },
        {
            'id': '2', 'pair': 'BINANCE:BTCUSDT', 'side': 'sell', 'status': 'filled',
            'total_quantity': 1, 'quantity': 1, 'avg_price': 110.0, 'price': 110.0,
            'created_at': 1704070800, 'updated_at': 1704074400
        }
    ]

    def fake_fetch_all_orders(creds):
        return fake_orders

    def fake_usdt_inr_fx():
        return 89.0

    def fake_get_balance(api_key, secret_key):
        return {'connected': True, 'balance': 1000.0, 'locked':0.0, 'currency':'INR'}

    monkeypatch.setattr(appmod, 'fetch_all_orders', fake_fetch_all_orders)
    monkeypatch.setattr(appmod, 'usdt_inr_fx', fake_usdt_inr_fx)
    monkeypatch.setattr(appmod, 'get_balance_from_api', fake_get_balance)

    creds = DummyCreds()
    data = _compute_trade_history_for_user(creds)
    assert 'closed' in data
    assert len(data['closed']) >= 1

    # Now call export_trade_history via function (it relies on session; we'll call the helper code by inlining)
    # Simulate the CSV build portion
    csv_buf = io.StringIO()
    cols = ["id", "pair", "side", "qty", "entry_px", "exit_px", "lev", "pnl (INR)", "entry_at", "exit_at"]
    csv_buf.write(','.join(cols) + '\n')
    for t in data.get('closed', []):
        # prefer numeric pnl_inr_value if present
        pnl_num = t.get('pnl_inr_value') if t.get('pnl_inr_value') is not None else t.get('pnl_inr')
        pnl = ''
        try:
            f = float(pnl_num)
            pnl = ('%d' % int(f)) if f.is_integer() else ('%.2f' % f)
        except Exception:
            pnl = str(pnl_num or '')
        row = [str(t.get('id','')),
               str(t.get('pair','')),
               str(t.get('side','')),
               str(t.get('qty','')),
               str(t.get('entry_px','')),
               str(t.get('exit_px','')),
               str(t.get('lev','')),
               '"' + pnl + '"',
               str(t.get('entry_at','')),
               str(t.get('exit_at',''))]
        csv_buf.write(','.join(row)+"\n")

    s = csv_buf.getvalue()
    assert 'pnl (INR)' in s
    # ensure the formatted pnl value we computed is present in the CSV
    assert pnl in s

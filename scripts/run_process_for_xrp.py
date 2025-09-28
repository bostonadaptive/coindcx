"""Test helper: emulate an authenticated session and force processing for config id 4 (XRPUSDT)
Requires this to be run in dev environment. Sets TEST_ACTIONS=1 to enable test-only processing.
"""
import os
import importlib.util
import sys
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# load app
spec = importlib.util.spec_from_file_location('app', os.path.join(ROOT, 'app.py'))
app_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app_mod)
app = getattr(app_mod, 'app')
from model import db, UserStrategySetup, StrategySignal, PaperTrade

# Ensure TEST_ACTIONS is enabled for this process
os.environ['TEST_ACTIONS'] = '1'

with app.test_client() as c:
    # Emulate login: pick the first user from DB (id=1 typically) and set session user_id
    with c.session_transaction() as sess:
        # find user id 1 exists
        sess['user_id'] = 1
    # make POST to algo_setup/signals with process flag
    r = c.post('/algo_setup/signals', json={'ids': [4], 'process': True}, headers={'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'})
    print('POST status:', r.status_code, r.get_data(as_text=True)[:1000])

    # Now check DB for StrategySignal and PaperTrade for config 4
    # Use app context to run queries
    with app.app_context():
        db.session.expire_all()
        sigs = StrategySignal.query.filter_by(strategy_id=None).all()  # broad fallback
        # More specific: find signals with symbol matching XRP
        x_sigs = StrategySignal.query.filter(StrategySignal.symbol.like('%XRP%')).all()
        p_trades = PaperTrade.query.filter(PaperTrade.config_id == 4).all()
        print('StrategySignals matching XRP:', [(s.id, s.symbol, s.status, s.direction, s.entry_price) for s in x_sigs])
        print('PaperTrades for config 4:', [(p.id, p.status, p.side, p.entry_price, p.paper_order_id) for p in p_trades])

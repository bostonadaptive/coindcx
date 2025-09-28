# Script to open a test paper BUY trade for ETHUSDT with margin=5000 and leverage=40
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, process_paper_signal
from model import User, UserStrategySetup, PaperWallet, PaperTrade
from datetime import datetime

with app.app_context():
    # create test user
    u = User(email='test_paper@example.com', password='x')
    db.session.add(u)
    db.session.commit()

    # create paper wallet
    w = PaperWallet(user_id=u.id, balance=100000.0, available_balance=100000.0, realized_pnl=0.0, unrealized_pnl=0.0)
    db.session.add(w)
    db.session.commit()

    # create user strategy setup
    us = UserStrategySetup(user_id=u.id, symbol='ETHUSDT', strategy_id=None, margin=5000.0, leverage=40, timeframe='15m', is_active=True, is_paper=True)
    db.session.add(us)
    db.session.commit()

    # pick a test LTP (use 1000 for qty math example)
    ltp = 1000.0

    # call process_paper_signal to open BUY with trend_confirmed True
    process_paper_signal(us, 'BUY', ltp, 'test-strategy', trend_confirmed=True)

    # fetch created trade
    pt = PaperTrade.query.filter_by(user_id=u.id).order_by(PaperTrade.id.desc()).first()
    if pt:
        print('Created PaperTrade:')
        print('id:', pt.id)
        print('user_id:', pt.user_id)
        print('symbol:', pt.symbol)
        print('side:', pt.side)
        print('entry_price:', pt.entry_price)
        print('qty:', pt.qty)
        print('margin:', pt.margin)
        print('leverage:', pt.leverage)
        print('locked_amount:', pt.locked_amount)
        print('status:', pt.status)
    else:
        print('No paper trade created')

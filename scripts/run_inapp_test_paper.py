import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, process_paper_signal
from model import User, UserStrategySetup, PaperWallet, PaperTrade
from datetime import datetime

with app.app_context():
    # find or create test user
    u = User.query.filter_by(email='test_paper@example.com').first()
    if not u:
        u = User(email='test_paper@example.com', password='x')
        db.session.add(u); db.session.commit()
        print('Created user', u.id)
    else:
        print('Found user', u.id)

    # ensure paper wallet exists
    w = PaperWallet.query.filter_by(user_id=u.id).first()
    if not w:
        w = PaperWallet(user_id=u.id, balance=100000.0, available_balance=100000.0, realized_pnl=0.0, unrealized_pnl=0.0)
        db.session.add(w); db.session.commit()
        print('Created wallet', w.id)
    else:
        print('Wallet exists', w.id, 'available', w.available_balance)

    # remove any existing active setup for this symbol
    existing_us = UserStrategySetup.query.filter_by(user_id=u.id, symbol='ETHUSDT').first()
    if existing_us:
        UserStrategySetup.query.filter_by(user_id=u.id, symbol='ETHUSDT').delete(); db.session.commit()

    # create new setup
    us = UserStrategySetup(user_id=u.id, symbol='ETHUSDT', strategy_id=None, margin=5000.0, leverage=40, timeframe='15m', is_active=True, is_paper=True)
    db.session.add(us); db.session.commit()
    print('Created UserStrategySetup', us.id)

    # call process_paper_signal
    process_paper_signal(us, 'BUY', 1000.0, 'test-strategy', trend_confirmed=True)
    db.session.commit()
    print('Called process_paper_signal')

    # inspect created trade and wallet
    pt = PaperTrade.query.filter_by(user_id=u.id).order_by(PaperTrade.id.desc()).first()
    if pt:
        print('PaperTrade created:', pt.id, pt.symbol, pt.side, pt.qty, pt.entry_price, pt.margin, pt.leverage, pt.locked_amount, pt.status)
    else:
        print('No PaperTrade created')
    w = PaperWallet.query.filter_by(user_id=u.id).first()
    print('Wallet now:', w.id, w.balance, w.available_balance, w.realized_pnl, w.unrealized_pnl)

import os, sys, traceback
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, process_paper_signal
from model import User, UserStrategySetup, PaperWallet, PaperTrade, Strategy

print('Starting debug script')
with app.app_context():
    try:
        print('In app context')
        u = User.query.filter_by(email='test_paper@example.com').first()
        if not u:
            u = User(email='test_paper@example.com', password='x')
            db.session.add(u); db.session.commit()
            print('Created user', u.id)
        else:
            print('Found user', u.id)

        w = PaperWallet.query.filter_by(user_id=u.id).first()
        if not w:
            w = PaperWallet(user_id=u.id, balance=100000.0, available_balance=100000.0, realized_pnl=0.0, unrealized_pnl=0.0)
            db.session.add(w); db.session.commit()
            print('Created wallet', w.id)
        else:
            print('Wallet exists', w.id, 'available', w.available_balance)

        # create a Strategy if missing
        strat = Strategy.query.filter_by(name='test-strategy').first()
        if not strat:
            strat = Strategy(name='test-strategy', description='debug', signals='test', timeframe='15m')
            db.session.add(strat); db.session.commit()
            print('Created Strategy', strat.id)
        else:
            print('Found Strategy', strat.id)

        # create setup
        existing = UserStrategySetup.query.filter_by(user_id=u.id, symbol='ETHUSDT').first()
        if existing:
            print('Deleting existing setup', existing.id)
            db.session.delete(existing); db.session.commit()

        us = UserStrategySetup(user_id=u.id, symbol='ETHUSDT', strategy_id=strat.id, margin=5000.0, leverage=40, timeframe='15m', is_active=True, is_paper=True)
        db.session.add(us); db.session.commit()
        print('Created setup', us.id)

        print('Calling process_paper_signal...')
        try:
            process_paper_signal(us, 'BUY', 1000.0, 'test-strategy', trend_confirmed=True)
            db.session.commit()
            print('process_paper_signal returned')
        except Exception as e:
            print('process_paper_signal raised:', repr(e))
            traceback.print_exc()

        pt = PaperTrade.query.filter_by(user_id=u.id).order_by(PaperTrade.id.desc()).first()
        if pt:
            print('PaperTrade created:', pt.id, pt.symbol, pt.side, pt.qty, pt.entry_price, pt.margin, pt.leverage, pt.locked_amount, pt.status)
        else:
            print('No PaperTrade created')

        w = PaperWallet.query.filter_by(user_id=u.id).first()
        print('Wallet now:', w.id, w.balance, w.available_balance, w.realized_pnl, w.unrealized_pnl)

    except Exception as e:
        print('Outer exception:', repr(e))
        traceback.print_exc()

print('Debug script finished')

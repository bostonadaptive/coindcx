import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db
from model import User, PaperTrade, PaperWallet

with app.app_context():
    u = User.query.filter_by(email='test_paper@example.com').first()
    if not u:
        print('No test user found')
    else:
        print('User:', u.id, u.email)
        w = PaperWallet.query.filter_by(user_id=u.id).first()
        if w:
            print('Wallet:', w.id, 'balance=', w.balance, 'available=', w.available_balance, 'realized=', w.realized_pnl, 'unrealized=', w.unrealized_pnl)
        else:
            print('No wallet')
        pt = PaperTrade.query.filter_by(user_id=u.id).order_by(PaperTrade.id.desc()).first()
        if pt:
            print('PaperTrade:', pt.id, pt.symbol, pt.side, pt.qty, pt.entry_price, pt.margin, pt.leverage, pt.locked_amount, pt.status)
        else:
            print('No paper trade')

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app
from model import PaperTrade

with app.app_context():
    t = PaperTrade.query.order_by(PaperTrade.id.desc()).first()
    if not t:
        print('No trade found')
    else:
        print('Found trade:', t.id, t.symbol, t.side, t.status, t.qty, t.locked_amount, t.margin, t.leverage)

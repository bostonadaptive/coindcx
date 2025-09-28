import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, db
from model import PaperTrade

DB = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'instance', 'coindcx.db'))
print('Using DB:', DB)

with app.app_context():
    try:
        rows = PaperTrade.query.order_by(PaperTrade.id.desc()).limit(1).all()
        print('Success, found', len(rows), 'rows')
        for r in rows:
            print(r.id, r.symbol, r.margin, r.leverage, r.locked_amount)
    except Exception as e:
        print('Error:', repr(e))

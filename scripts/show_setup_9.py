import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app
from model import db, UserStrategySetup

with app.app_context():
    us=db.session.get(UserStrategySetup,9)
    if not us:
        print('not found')
    else:
        print(us.id, us.user_id, us.symbol, us.is_active, us.is_paper)

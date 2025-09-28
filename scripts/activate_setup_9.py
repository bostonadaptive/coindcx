import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app
from model import db, UserStrategySetup

with app.app_context():
    us = db.session.get(UserStrategySetup, 9)
    if not us:
        print('UserStrategySetup id=9 not found')
    else:
        us.is_active = True
        us.is_paper = True
        db.session.commit()
        print(f'Activated setup {us.id}: is_active={us.is_active} is_paper={us.is_paper}')

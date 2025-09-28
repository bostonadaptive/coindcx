import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db
from model import User

with app.app_context():
    u = User.query.filter_by(email='test@example.com').first()
    if not u:
        print('no user')
    else:
        print('user id', u.id)
        print('password hash', u.password)

"""
Seed the database with a test user and one strategy + user strategy setup for that user.
Usage:
  python scripts/_seed_test_user_strategy.py --email test@example.com --password password123
If email not provided, a timestamped email is used. Prints created email/password on success.
"""
import os
import sys
import argparse
# ensure project root is on sys.path so imports like `from app import app` work when running this script
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db
from model import User, Strategy, UserStrategySetup
from werkzeug.security import generate_password_hash
from datetime import datetime


def seed(email=None, password='password123'):
    if not email:
        email = 'ptest+' + datetime.utcnow().strftime('%Y%m%d%H%M%S') + '@example.com'
    with app.app_context():
        db.create_all()
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(email=email, password=generate_password_hash(password))
            db.session.add(user)
            db.session.commit()
            print('Created user', email)
        else:
            print('User exists', email)
        # ensure a Strategy exists
        strat = Strategy.query.filter_by(name='SmokeTestStrategy').first()
        if not strat:
            strat = Strategy(name='SmokeTestStrategy', description='Auto-created for smoke tests', signals='1-1', timeframe='15m')
            db.session.add(strat)
            db.session.commit()
            print('Created strategy SmokeTestStrategy')
        # ensure user strategy setup exists
        uset = UserStrategySetup.query.filter_by(user_id=user.id, strategy_id=strat.id).first()
        if not uset:
            uset = UserStrategySetup(user_id=user.id, symbol='BTCUSDT.P', strategy_id=strat.id, leverage=1, margin=1000.0, timeframe='15m', is_active=False)
            db.session.add(uset)
            db.session.commit()
            print('Created UserStrategySetup for user', email)
        else:
            print('UserStrategySetup already exists for user')
    return email, password

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--email', help='Email to create', default=None)
    parser.add_argument('--password', help='Password', default='password123')
    args = parser.parse_args()
    e, p = seed(args.email, args.password)
    print('Seed complete. Use TEST_EMAIL and TEST_PASSWORD env vars to run Playwright tests against this user:')
    print(e, p)

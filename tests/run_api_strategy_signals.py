import json
import os, sys
# ensure project root is on sys.path so we can import app and model
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db
from model import User, UserStrategySetup

# Quick script to call /api/strategy_signals using Flask test client.
# It assumes a user exists in the DB. If multiple users exist, the script
# will pick the first user and set session['user_id'] via the test client.

with app.test_client() as client:
    # find a user id
    with app.app_context():
        u = db.session.query(User).first()
        if not u:
            print('No users found in DB. Create a user and retry.')
            raise SystemExit(1)
        uid = u.id
        print('Using user id:', uid)

    # set session by logging in via test client (set cookie directly)
    with client.session_transaction() as sess:
        sess['user_id'] = uid

    resp = client.get('/api/strategy_signals')
    print('Status:', resp.status_code)
    try:
        data = resp.get_json()
        print(json.dumps(data, indent=2, default=str))
    except Exception as e:
        print('Failed to parse JSON:', e)
        print(resp.data)

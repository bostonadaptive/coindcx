import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db
from model import User
from werkzeug.security import generate_password_hash, check_password_hash

EMAIL='test@example.com'
NEW='password123'

with app.app_context():
    u = User.query.filter_by(email=EMAIL).first()
    if not u:
        print('No user', EMAIL)
        sys.exit(1)
    print('Found user id', u.id)
    ok = check_password_hash(u.password, NEW)
    print('Password matches already?', ok)
    if not ok:
        print('Updating password to', NEW)
        u.password = generate_password_hash(NEW)
        db.session.commit()
        print('Updated.')
    else:
        print('No update needed')

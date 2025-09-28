from app import app, db
from model import User, Credentials

with app.app_context():
    u = User.query.filter_by(email='smoke_test_user@example.com').first()
    if not u:
        print('User not found')
    else:
        c = Credentials.query.filter_by(user_id=u.id).first()
        if not c:
            c = Credentials(user_id=u.id, api_key='FAKEKEY123', secret_key='FAKESECRET456')
            db.session.add(c)
            db.session.commit()
            print('Added credentials for user', u.id)
        else:
            c.api_key = 'FAKEKEY123'
            c.secret_key = 'FAKESECRET456'
            db.session.commit()
            print('Updated creds for', u.id)

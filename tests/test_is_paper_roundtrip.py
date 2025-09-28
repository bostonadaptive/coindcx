import os
import tempfile
import pytest
import uuid
from app import app, db
from model import UserStrategySetup, User, Strategy


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    # use a temporary sqlite db for tests
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{db_path}"
    with app.test_client() as client:
        with app.app_context():
            db.create_all()
        yield client
    os.close(db_fd)
    try:
        os.unlink(db_path)
    except Exception:
        pass


def test_is_paper_add_edit_roundtrip(client):
    # Prepare DB: create a user and a Strategy that add_algo_strategy will reference
    with app.app_context():
        # use unique email to avoid collisions between test runs
        user = User(email=f't+{uuid.uuid4().hex}@example.com', password='x', role_id=3)
        db.session.add(user)
        db.session.commit()
        strat_name = f"test-strat-{uuid.uuid4().hex}"
        strat = Strategy(name=strat_name, is_active=True)
        db.session.add(strat)
        db.session.commit()
        user_id = user.id

    # Set session user_id so login_required and add/edit handlers see the user
    with client.session_transaction() as sess:
        sess['user_id'] = user_id

    # 1) Add a new strategy with is_paper=1
    add_data = {
        'strategy_name': strat_name,
        'symbol_tv': 'BINANCE:BTCUSDT',
        'leverage': '1',
        'amount': '1000',
        'timeframe': '15m',
        'is_paper': '1',
    }
    resp = client.post('/add_algo_strategy', data=add_data, follow_redirects=True)
    # add redirects to algo_setup; expect success (200) on follow
    assert resp.status_code == 200

    # find the strategy
    with app.app_context():
        s = UserStrategySetup.query.filter_by(user_id=user_id).first()
        assert s is not None
        assert s.is_paper is True

        # 2) Edit the strategy to set is_paper=0
        edit_url = f"/algo_setup/{s.id}/edit"

    edit_data = {
        'strategy_name': strat_name,
        'symbol_tv': 'BINANCE:BTCUSDT',
        'leverage': '1',
        'amount': '1000',
        'timeframe': '15m',
        'is_paper': '0',
    }
    resp2 = client.post(edit_url, data=edit_data, follow_redirects=True)
    assert resp2.status_code == 200

    with app.app_context():
        s2 = UserStrategySetup.query.get(s.id)
        assert s2 is not None
        assert s2.is_paper is False

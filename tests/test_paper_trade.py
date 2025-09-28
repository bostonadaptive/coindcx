import pytest
from datetime import datetime
import uuid

from app import app, db
from model import PaperTrade, PaperWallet, User, UserStrategySetup

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.app_context():
        db.create_all()
        yield app.test_client()


def setup_user_and_setup():
    email = f"t+{uuid.uuid4().hex}@example.com"
    u = User(email=email, password='x')
    db.session.add(u)
    db.session.commit()
    # create a Strategy record and reference it (strategy_id is NOT NULL in model)
    from model import Strategy
    strat = Strategy(name=f"strat-{uuid.uuid4().hex}", is_active=True)
    db.session.add(strat)
    db.session.commit()
    us = UserStrategySetup(user_id=u.id, symbol='BTCUSDT', strategy_id=strat.id, margin=1000.0, leverage=1, is_active=True, is_paper=True)
    db.session.add(us)
    db.session.commit()
    return u, us


def test_open_close_long_and_wallet(client):
    with app.app_context():
        u, us = setup_user_and_setup()
        wallet = PaperWallet(user_id=u.id, balance=100000.0, available_balance=100000.0)
        db.session.add(wallet)
        db.session.commit()

        # simulate BUY signal with trend_confirmed True
        from app import process_paper_signal
        process_paper_signal(us, 'BUY', 50000.0, 'test', trend_confirmed=True)
        pt = PaperTrade.query.filter_by(user_id=u.id).first()
        assert pt is not None
        assert pt.side == 'BUY'
        assert pt.status == 'OPEN'
        # available balance reduced by margin
        w = PaperWallet.query.filter_by(user_id=u.id).first()
        assert w.available_balance < w.balance

        # simulate SELL to close
        process_paper_signal(us, 'SELL', 51000.0, 'test', trend_confirmed=True)
        pt = PaperTrade.query.filter_by(user_id=u.id).first()
        assert pt.status == 'CLOSED'
        w = PaperWallet.query.filter_by(user_id=u.id).first()
        assert w.realized_pnl != 0


def test_open_close_short_and_wallet(client):
    with app.app_context():
        u, us = setup_user_and_setup()
        wallet = PaperWallet(user_id=u.id, balance=100000.0, available_balance=100000.0)
        db.session.add(wallet)
        db.session.commit()

        from app import process_paper_signal
        # simulate SELL to open short
        process_paper_signal(us, 'SELL', 50000.0, 'test', trend_confirmed=True)
        pt = PaperTrade.query.filter_by(user_id=u.id, side='SELL').first()
        assert pt is not None and pt.status == 'OPEN'

        # simulate BUY to close short
        process_paper_signal(us, 'BUY', 49000.0, 'test', trend_confirmed=True)
        pt = PaperTrade.query.filter_by(user_id=u.id).first()
        assert pt.status == 'CLOSED'
        w = PaperWallet.query.filter_by(user_id=u.id).first()
        assert w.realized_pnl != 0


def test_insufficient_funds_prevent_open(client):
    with app.app_context():
        u, us = setup_user_and_setup()
        # make wallet with small available balance
        wallet = PaperWallet(user_id=u.id, balance=100.0, available_balance=100.0)
        db.session.add(wallet)
        db.session.commit()
        from app import process_paper_signal
        # margin=1000 in setup -> insufficient funds should prevent opening
        process_paper_signal(us, 'BUY', 50000.0, 'test', trend_confirmed=True)
        pt = PaperTrade.query.filter_by(user_id=u.id).first()
        assert pt is None


def test_prevent_multiple_open_trades(client):
    with app.app_context():
        u, us = setup_user_and_setup()
        wallet = PaperWallet(user_id=u.id, balance=100000.0, available_balance=100000.0)
        db.session.add(wallet)
        db.session.commit()
        from app import process_paper_signal
        process_paper_signal(us, 'BUY', 50000.0, 'test', trend_confirmed=True)
        first = PaperTrade.query.filter_by(user_id=u.id, status='OPEN').first()
        assert first is not None
        # Try opening again; should not create duplicate open trade
        process_paper_signal(us, 'BUY', 50010.0, 'test', trend_confirmed=True)
        opens = PaperTrade.query.filter_by(user_id=u.id, status='OPEN').all()
        assert len(opens) == 1


def test_partial_close_behavior(client):
    with app.app_context():
        u, us = setup_user_and_setup()
        wallet = PaperWallet(user_id=u.id, balance=100000.0, available_balance=100000.0)
        db.session.add(wallet)
        db.session.commit()
        from app import process_paper_signal
        # open large position
        process_paper_signal(us, 'BUY', 100.0, 'test', trend_confirmed=True)
        pt = PaperTrade.query.filter_by(user_id=u.id, status='OPEN').first()
        assert pt is not None
        # simulate partial manual reduce of qty (partial close) and then close
        pt.qty = pt.qty / 2.0
        db.session.commit()
        # now close with SELL
        process_paper_signal(us, 'SELL', 110.0, 'test', trend_confirmed=True)
        pt = PaperTrade.query.filter_by(user_id=u.id).first()
        assert pt.status == 'CLOSED'
        w = PaperWallet.query.filter_by(user_id=u.id).first()
        assert w.realized_pnl != 0

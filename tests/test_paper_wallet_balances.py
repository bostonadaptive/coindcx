import pytest
import uuid
from datetime import datetime

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
    from model import Strategy
    strat = Strategy(name=f"strat-{uuid.uuid4().hex}", is_active=True)
    db.session.add(strat)
    db.session.commit()
    us = UserStrategySetup(user_id=u.id, symbol='BTCUSDT', strategy_id=strat.id, margin=1000.0, leverage=1, is_active=True, is_paper=True)
    db.session.add(us)
    db.session.commit()
    return u, us


def test_wallet_balances_after_open_and_close_buy(client):
    """Open a BUY, assert available reduced by margin, then close with profit and assert balances update."""
    with app.app_context():
        u, us = setup_user_and_setup()
        wallet = PaperWallet(user_id=u.id, balance=100000.0, available_balance=100000.0)
        db.session.add(wallet)
        db.session.commit()

        from app import process_paper_signal
        # Open BUY at 50k
        process_paper_signal(us, 'BUY', 50000.0, 'test', trend_confirmed=True)
        pt = PaperTrade.query.filter_by(user_id=u.id, status='OPEN').first()
        assert pt is not None and pt.side == 'BUY'
        w = PaperWallet.query.filter_by(user_id=u.id).first()
        # available reduced by margin (1000)
        assert float(w.available_balance) == float(100000.0 - 1000.0)

        # Close BUY at 51000 -> profit = (51000-50000)*qty
        # qty = margin * leverage / entry_price = 1000/50000 = 0.02
        expected_qty = 1000.0 / 50000.0
        assert abs(float(pt.qty) - expected_qty) < 1e-9

        process_paper_signal(us, 'SELL', 51000.0, 'test', trend_confirmed=True)
        pt = PaperTrade.query.filter_by(user_id=u.id).first()
        assert pt.status == 'CLOSED'
        w = PaperWallet.query.filter_by(user_id=u.id).first()
        # pnl = (51000-50000)*qty = 1000 * qty = 1000 * (1000/50000) = 20.0
        expected_pnl = (51000.0 - 50000.0) * expected_qty
        assert abs(float(w.realized_pnl) - expected_pnl) < 1e-6
        # available_balance should be previous available (100000-1000) + locked_amount(1000) + pnl
        expected_available = (100000.0 - 1000.0) + 1000.0 + expected_pnl
        assert abs(float(w.available_balance) - expected_available) < 1e-6


def test_wallet_balances_after_open_and_close_sell(client):
    """Open a SELL (short), assert available reduced by margin, then close with profit and assert balances update."""
    with app.app_context():
        u, us = setup_user_and_setup()
        wallet = PaperWallet(user_id=u.id, balance=50000.0, available_balance=50000.0)
        db.session.add(wallet)
        db.session.commit()

        from app import process_paper_signal
        # Open SELL at 50k
        process_paper_signal(us, 'SELL', 50000.0, 'test', trend_confirmed=True)
        pt = PaperTrade.query.filter_by(user_id=u.id, status='OPEN', side='SELL').first()
        assert pt is not None
        w = PaperWallet.query.filter_by(user_id=u.id).first()
        assert float(w.available_balance) == float(50000.0 - 1000.0)

        expected_qty = 1000.0 / 50000.0
        assert abs(float(pt.qty) - expected_qty) < 1e-9

        # Close SELL at 49000 -> profit = (entry - exit) * qty = (50000-49000)*qty
        process_paper_signal(us, 'BUY', 49000.0, 'test', trend_confirmed=True)
        pt = PaperTrade.query.filter_by(user_id=u.id).first()
        assert pt.status == 'CLOSED'
        w = PaperWallet.query.filter_by(user_id=u.id).first()
        expected_pnl = (50000.0 - 49000.0) * expected_qty
        assert abs(float(w.realized_pnl) - expected_pnl) < 1e-6
        expected_available = (50000.0 - 1000.0) + 1000.0 + expected_pnl
        assert abs(float(w.available_balance) - expected_available) < 1e-6

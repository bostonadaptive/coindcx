import pytest
import os, sys, uuid

# Ensure project root is importable when running a single test file
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app, db
from model import User, UserStrategySetup, Strategy, PaperTrade, PaperWallet, StrategySignal


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
    strat = Strategy(name=f"strat-{uuid.uuid4().hex}", is_active=True)
    db.session.add(strat)
    db.session.commit()
    us = UserStrategySetup(user_id=u.id, symbol='BTCUSDT', strategy_id=strat.id, margin=1000.0, leverage=1, is_active=True, is_paper=True)
    db.session.add(us)
    db.session.commit()
    return u, us


def test_e2e_entry_exit_reasons(client):
    """End-to-end check: entry_reason 'hammer' and exit_reason 'shooting_star' are persisted."""
    with app.app_context():
        u, us = setup_user_and_setup()
        wallet = PaperWallet(user_id=u.id, balance=100000.0, available_balance=100000.0)
        db.session.add(wallet)
        db.session.commit()

        from app import process_paper_signal

        # Open with explicit entry reason
        process_paper_signal(us, 'BUY', 100.0, 'test', trend_confirmed=True, entry_reason='hammer')
        pt = PaperTrade.query.filter_by(user_id=u.id).first()
        print(f"PAPERTRADE_ENTRY_ROW: id={pt.id}, entry_reason={pt.entry_reason}, side={pt.side}, status={pt.status}")
        assert pt is not None
        assert pt.entry_reason == 'hammer'

        # Close with explicit exit reason hint
        process_paper_signal(us, 'SELL', 110.0, 'test', trend_confirmed=True, exit_reason_hint='shooting_star')
        pt2 = PaperTrade.query.filter_by(user_id=u.id).first()
        print(f"PAPERTRADE_EXIT_ROW: id={pt2.id}, exit_reason={pt2.exit_reason}, status={pt2.status}")
        assert pt2.status == 'CLOSED'
        assert pt2.exit_reason == 'shooting_star'

        # Verify StrategySignal persisted reasons as well
        ss = StrategySignal.query.filter_by(strategy_id=us.strategy_id, symbol=us.symbol).order_by(StrategySignal.entry_time.desc()).first()
        print(f"STRATEGYSIGNAL_ROW: id={ss.id if ss else None}, entry_reason={getattr(ss, 'entry_reason', None)}, exit_reason={getattr(ss, 'exit_reason', None)}")
        assert ss is not None
        assert ss.entry_reason == 'hammer'
        assert ss.exit_reason == 'shooting_star'

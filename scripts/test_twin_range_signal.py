import os, sys
# Ensure project root is on sys.path when executed from scripts/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, db, _compute_signal_for_user_strategy
from model import User, Strategy, UserStrategySetup
import pandas as pd
from technical_strategies import twin_range_filter_strategy

if __name__ == '__main__':
    with app.app_context():
        # create or get test user
        u = User.query.filter_by(email='test_trend_user@example.com').first()
        if not u:
            u = User(email='test_trend_user@example.com', password='x')
            db.session.add(u)
            db.session.commit()
            print('Created test user:', u.email)
        else:
            print('Using existing user:', u.email)

        strat = Strategy.query.filter_by(name='Twin Range Filter').first()
        if not strat:
            print('Strategy Twin Range Filter not found')
            raise SystemExit(1)
        else:
            print('Found strategy:', strat.name)

        # create or reuse setup
        us = UserStrategySetup.query.filter_by(user_id=u.id, strategy_id=strat.id, symbol='BINANCE:BTCUSDT').first()
        if not us:
            us = UserStrategySetup(user_id=u.id, strategy_id=strat.id, symbol='BINANCE:BTCUSDT', leverage=1, margin=1000, timeframe='15m', is_active=False)
            db.session.add(us)
            db.session.commit()
            print('Created UserStrategySetup id=', us.id)
        else:
            print('Using existing UserStrategySetup id=', us.id)

        print('Computing live signal (may attempt network fetch)...')
        try:
            sig = _compute_signal_for_user_strategy(us, strat)
        except Exception as e:
            sig = None
            print('Live computation raised:', e)
        print('Computed signal for Twin Range Filter on BINANCE:BTCUSDT ->', sig)

        # If live computation is not actionable, run the strategy on synthetic rising/falling data
        if sig in (None, '-', 'Waiting...', 'HOLD'):
            print('Live signal not actionable; running local synthetic dataset to demonstrate signals...')
            # build synthetic rising close series to trigger a long signal
            n = 300
            base = 30000.0
            inc = 0.2
            closes = [base + i*inc for i in range(n)]
            df = pd.DataFrame({
                'open': closes,
                'high': [c + 1.0 for c in closes],
                'low': [c - 1.0 for c in closes],
                'close': closes,
            })
            out = twin_range_filter_strategy(df)
            last = out.iloc[-1]
            print('Synthetic run buy_signal=', bool(last.get('buy_signal')), 'sell_signal=', bool(last.get('sell_signal')))

import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, db, _compute_signal_for_user_strategy
from app import fetch_candles as real_fetch_candles
from model import User, Strategy, UserStrategySetup

# Synthetic candle generator: rising close series
def synthetic_candles(pair_market, timeframe, start_dt, end_dt):
    n = 300
    base = 30000.0
    inc = 0.5
    out = []
    t0 = 1600000000
    for i in range(n):
        c = base + i * inc
        out.append({'t': t0 + i*60, 'o': c - 0.1, 'h': c + 1.0, 'l': c - 1.0, 'c': c})
    return out

if __name__ == '__main__':
    with app.app_context():
        u = User.query.filter_by(email='test_trend_user@example.com').first()
        if not u:
            u = User(email='test_trend_user@example.com', password='x')
            db.session.add(u); db.session.commit(); print('Created test user')
        strat = Strategy.query.filter_by(name='Twin Range Filter').first()
        if not strat:
            print('Strategy missing'); raise SystemExit(1)
        us = UserStrategySetup.query.filter_by(user_id=u.id, strategy_id=strat.id, symbol='BINANCE:BTCUSDT').first()
        if not us:
            us = UserStrategySetup(user_id=u.id, strategy_id=strat.id, symbol='BINANCE:BTCUSDT', leverage=1, margin=1000, timeframe='15m')
            db.session.add(us); db.session.commit(); print('Created setup')

        # Monkeypatch fetch_candles in app module
        try:
            import app as app_module
            app_module.fetch_candles = synthetic_candles
            print('Patched app.fetch_candles with synthetic generator')
        except Exception as e:
            print('Failed to patch fetch_candles:', e)

        sig = _compute_signal_for_user_strategy(us, strat)
        print('Smoke test computed signal for Twin Range Filter ->', sig)

        # restore original if needed
        try:
            app_module.fetch_candles = real_fetch_candles
        except Exception:
            pass

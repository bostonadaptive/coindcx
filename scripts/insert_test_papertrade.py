import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db
from model import PaperTrade, UserStrategySetup, Strategy
from datetime import datetime, timedelta

# Insert a closed PaperTrade for user_id=1, config_id=9 (or adjust if config doesn't exist)
with app.app_context():
    # verify config exists
    cfg = db.session.get(UserStrategySetup, 9)
    if not cfg:
        print('Config id 9 not found; listing first 5 configs:')
        rows = db.session.query(UserStrategySetup).limit(5).all()
        for r in rows:
            print('id=', r.id, 'user_id=', r.user_id, 'symbol=', r.symbol, 'is_paper=', r.is_paper, 'is_active=', r.is_active)
        raise SystemExit(1)

    strat_name = None
    try:
        s = db.session.get(Strategy, cfg.strategy_id) if cfg and cfg.strategy_id else None
        strat_name = s.name if s else ''
    except Exception:
        strat_name = ''

    pt = PaperTrade(
        user_id=1,
        config_id=9,
        symbol=cfg.symbol,
        side='BUY',
        qty=1.0,
        entry_price=1000.0,
        entry_time=datetime.utcnow()-timedelta(minutes=5),
        exit_price=1100.0,
        exit_time=datetime.utcnow()-timedelta(minutes=1),
        margin=1000.0,
        leverage=1,
        locked_amount=1000.0,
        pnl_inr=100.0,
        status='CLOSED',
        strategy=str(strat_name or ''),
        paper_order_id='TEST-PAPER-1',
        )
    try:
        pt.exit_reason = 'Test backfill reason: closed by unit test script'
    except Exception:
        pass
    db.session.add(pt)
    db.session.commit()
    print('Inserted test PaperTrade id=', pt.id)

"""Run this to ensure the CREATE INDEX statements run against the on-disk SQLite DB.
This imports the Flask app and runs inside the app context so it works whether you used
`flask run` or not.
"""
from app import app, db
from sqlalchemy import text

idx_sql = [
    "CREATE INDEX IF NOT EXISTS idx_paper_trades_user_status ON paper_trades(user_id, status);",
    "CREATE INDEX IF NOT EXISTS idx_paper_trades_config_id ON paper_trades(config_id);",
    "CREATE INDEX IF NOT EXISTS idx_user_strategy_user_active ON user_strategy_setup(user_id, is_active);",
    "CREATE INDEX IF NOT EXISTS idx_user_strategy_symbol ON user_strategy_setup(symbol);",
    "CREATE INDEX IF NOT EXISTS idx_strategy_signals_strategy_symbol ON strategy_signals(strategy_id, symbol);",
    "CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id);",
    "CREATE INDEX IF NOT EXISTS idx_credentials_user ON credentials(user_id);",
]

with app.app_context():
    for s in idx_sql:
        try:
            db.session.execute(text(s))
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
    try:
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass

print("Index creation attempted")
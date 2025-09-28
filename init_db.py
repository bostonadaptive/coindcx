from app import app, db
with app.app_context():
    db.create_all()
    # Seed default strategies if missing
    try:
        from model import Strategy
        existing = Strategy.query.filter_by(name='Twin Range Filter').first()
        if not existing:
            s = Strategy(name='Twin Range Filter', description='Twin Range Filter strategy ported from PineScript (Twin Range Filter).', signals='1-1', difficulty='Medium', timeframe='15m', gain='N/A', is_active=True)
            db.session.add(s)
            db.session.commit()
            print("✅ Added Twin Range Filter strategy to strategies table")
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        print('Warning: failed to seed Twin Range Filter strategy:', e)
    print("✅ Tables created in coindcx.db")

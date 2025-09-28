# Simple smoke test to validate PaperTrade/PaperWallet model schema and DB create_all
import os, sys
# ensure project root is on sys.path (script runs from scripts/)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db
from model import PaperTrade, PaperWallet

if __name__ == '__main__':
    print('Starting smoke test')
    with app.app_context():
        try:
            db.create_all()
            print('db.create_all() ran')
            print('PaperTrade columns:', [c.name for c in PaperTrade.__table__.columns])
            print('PaperWallet columns:', [c.name for c in PaperWallet.__table__.columns])
        except Exception as e:
            print('Error during smoke test:', e)

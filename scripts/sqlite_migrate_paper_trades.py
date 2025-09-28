"""
Safe SQLite migration for `paper_trades` to add new columns (margin, leverage, locked_amount).
This script:
 - creates a backup copy of the DB
 - creates a new temporary table with desired schema
 - copies existing data mapping known columns
 - drops old table and renames the new one

Run: python sqlite_migrate_paper_trades.py
"""
import sqlite3
import shutil
import os

DB = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'instance', 'coindcx.db'))

def backup():
    bak = DB + '.bak_migrate'
    shutil.copy2(DB, bak)
    print('Backup:', bak)

def migrate():
    if not os.path.exists(DB):
        print('DB not found at', DB)
        return
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    try:
        cur.execute('PRAGMA foreign_keys=OFF')
        conn.commit()

        # check if columns already exist
        cur.execute("PRAGMA table_info('paper_trades')")
        cols = [r[1] for r in cur.fetchall()]
        need = [c for c in ('margin','leverage','locked_amount') if c not in cols]
        if not need:
            print('No migration needed; columns already present')
            return

        # create new table with desired schema
        cur.execute('''
        CREATE TABLE IF NOT EXISTS paper_trades_new (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            config_id INTEGER,
            symbol TEXT NOT NULL,
            tv_symbol TEXT,
            side TEXT,
            qty REAL DEFAULT 0.0,
            entry_price REAL,
            entry_time DATETIME,
            exit_price REAL,
            exit_time DATETIME,
            margin REAL DEFAULT 0.0,
            leverage INTEGER DEFAULT 1,
            locked_amount REAL DEFAULT 0.0,
            pnl_inr REAL DEFAULT 0.0,
            status TEXT DEFAULT 'OPEN',
            strategy TEXT
        )''')

        # copy data from old table if exists
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='paper_trades'")
        if cur.fetchone():
            # get common columns between old and new
            cur.execute("PRAGMA table_info('paper_trades')")
            old_cols = [r[1] for r in cur.fetchall()]
            # pick columns to copy that exist in old
            copy_cols = [c for c in ['id','user_id','config_id','symbol','tv_symbol','side','qty','entry_price','entry_time','exit_price','exit_time','pnl_inr','status','strategy'] if c in old_cols]
            col_list = ','.join(copy_cols)
            placeholders = ','.join(copy_cols)
            sql = f"INSERT INTO paper_trades_new ({col_list}) SELECT {col_list} FROM paper_trades"
            print('Copying data using:', sql)
            cur.execute(sql)

        # drop old and rename
        cur.execute('DROP TABLE IF EXISTS paper_trades')
        cur.execute('ALTER TABLE paper_trades_new RENAME TO paper_trades')

        conn.commit()
        print('Migration completed')
    except Exception as e:
        conn.rollback()
        print('Migration failed:', e)
    finally:
        cur.execute('PRAGMA foreign_keys=ON')
        conn.close()

if __name__ == '__main__':
    backup()
    migrate()

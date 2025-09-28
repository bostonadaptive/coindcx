import sqlite3
import os

DB = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'instance', 'coindcx.db'))
print('DB:', DB)
if not os.path.exists(DB):
    print('DB not found')
    raise SystemExit(1)
con = sqlite3.connect(DB)
cur = con.cursor()
cur.execute("PRAGMA table_info('strategy_signals')")
cols = [r[1] for r in cur.fetchall()]
print('strategy_signals columns:', cols)
if 'exit_reason' not in cols:
    print('Adding exit_reason column to strategy_signals...')
    cur.execute("ALTER TABLE strategy_signals ADD COLUMN exit_reason TEXT")
    con.commit()
    print('Column added')
else:
    print('Column already present')
con.close()
print('Done')

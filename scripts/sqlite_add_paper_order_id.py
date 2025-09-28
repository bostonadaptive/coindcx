#!/usr/bin/env python3
"""One-off utility: add paper_order_id to the local SQLite DB and backfill existing rows.

This is intended for local/dev convenience when Alembic can't be run against the current DB.
"""
import sqlite3
import uuid
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / 'instance' / 'coindcx.db'
print('DB path:', DB)
if not DB.exists():
    print('Database not found:', DB)
    raise SystemExit(1)

conn = sqlite3.connect(str(DB))
cur = conn.cursor()

# Check if column exists
try:
    cur.execute("PRAGMA table_info(paper_trades)")
    cols = [r[1] for r in cur.fetchall()]
    print('paper_trades columns:', cols)
    if 'paper_order_id' not in cols:
        print('Adding column paper_order_id...')
        cur.execute("ALTER TABLE paper_trades ADD COLUMN paper_order_id VARCHAR(80)")
        conn.commit()
    else:
        print('Column already present')

    # Backfill missing values
    cur.execute("SELECT id, paper_order_id FROM paper_trades")
    rows = cur.fetchall()
    to_update = []
    for r in rows:
        _id, val = r
        if val is None or val == '':
            to_update.append(_id)
    print('Rows to backfill:', len(to_update))
    for _id in to_update:
        new_val = 'PAPER-' + uuid.uuid4().hex
        cur.execute("UPDATE paper_trades SET paper_order_id = ? WHERE id = ?", (new_val, _id))
    conn.commit()
    print('Backfill complete')
    cur.execute("SELECT id, paper_order_id FROM paper_trades LIMIT 5")
    print(cur.fetchall())
except Exception as e:
    print('Error:', e)
finally:
    conn.close()

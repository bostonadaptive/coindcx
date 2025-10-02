"""
Simple helper to add `entry_reason` and `exit_reason` columns to `paper_trades` and `entry_reason` to `strategy_signals` if missing.
Run as:
  python sqlite_add_entry_exit_reason.py --db instance/coindcx.db --apply
or for dry-run:
  python sqlite_add_entry_exit_reason.py --db instance/coindcx.db
"""
import sqlite3
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--db', default='instance/coindcx.db')
parser.add_argument('--apply', action='store_true')
args = parser.parse_args()

conn = sqlite3.connect(args.db)
cur = conn.cursor()

# utility
def has_col(table, col):
    cur.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]
    return col in cols

changes = []

# paper_trades: add entry_reason and exit_reason
if not has_col('paper_trades', 'entry_reason'):
    changes.append("ALTER TABLE paper_trades ADD COLUMN entry_reason TEXT")
if not has_col('paper_trades', 'exit_reason'):
    changes.append("ALTER TABLE paper_trades ADD COLUMN exit_reason TEXT")

# strategy_signals: add entry_reason if missing
if not has_col('strategy_signals', 'entry_reason'):
    changes.append("ALTER TABLE strategy_signals ADD COLUMN entry_reason TEXT")

print('Planned changes:')
for c in changes:
    print('  ', c)

if args.apply and changes:
    for c in changes:
        print('Applying:', c)
        cur.execute(c)
    conn.commit()
    print('Done')
else:
    if not changes:
        print('No changes required')
    else:
        print('Run with --apply to apply changes')

cur.close()
conn.close()

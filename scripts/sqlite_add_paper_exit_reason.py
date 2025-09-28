import sqlite3
import os

DB = os.path.join(os.path.dirname(__file__), '..', 'instance', 'coindcx.db')
DB = os.path.abspath(DB)

print('DB path:', DB)
if not os.path.exists(DB):
    print('Database not found at', DB)
    raise SystemExit(1)

con = sqlite3.connect(DB)
cur = con.cursor()

# check if column exists
cur.execute("PRAGMA table_info('paper_trades')")
cols = [r[1] for r in cur.fetchall()]
print('paper_trades columns:', cols)
if 'exit_reason' not in cols:
    print('Adding exit_reason column to paper_trades...')
    try:
        cur.execute("ALTER TABLE paper_trades ADD COLUMN exit_reason TEXT")
        con.commit()
        print('Column added')
    except Exception as e:
        print('Failed to add column:', e)
        con.close()
        raise
else:
    print('exit_reason column already present')

# Backfill from trade_history: pick most recent trade_history.exit_reason for same user_id and symbol
print('Backfilling exit_reason from trade_history where available...')
cur.execute("SELECT id, user_id, symbol, exit_time FROM paper_trades WHERE exit_reason IS NULL OR exit_reason = ''")
rows = cur.fetchall()
print('Rows to consider:', len(rows))
updated = 0
for r in rows:
    pid, uid, sym, p_exit_time = r
    # find trade_history row with same user_id and symbol and closest close_time to paper_trades.exit_time
    cur.execute(
        "SELECT exit_reason, close_time FROM trade_history WHERE user_id = ? AND symbol = ? AND exit_reason IS NOT NULL ORDER BY close_time DESC LIMIT 1",
        (uid, sym)
    )
    th = cur.fetchone()
    if th and th[0]:
        exit_reason = th[0]
        try:
            cur.execute("UPDATE paper_trades SET exit_reason = ? WHERE id = ?", (exit_reason, pid))
            updated += 1
        except Exception:
            continue

if updated:
    con.commit()
print('Backfilled rows:', updated)
con.close()
print('Done')

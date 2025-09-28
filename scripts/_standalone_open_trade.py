import sqlite3, os
from datetime import datetime
DB=os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'instance', 'coindcx.db'))
conn=sqlite3.connect(DB)
cur=conn.cursor()
user_email='test_paper@example.com'
cur.execute('SELECT id FROM users WHERE email=?', (user_email,))
row=cur.fetchone()
if not row:
    print('User not found')
    conn.close(); exit(1)
uid=row[0]
print('User id', uid)
# ensure wallet
cur.execute('SELECT id, available_balance FROM paper_wallet WHERE user_id=?', (uid,))
w=cur.fetchone()
if not w:
    print('No wallet; creating')
    cur.execute('INSERT INTO paper_wallet (user_id, balance, realized_pnl, unrealized_pnl, available_balance) VALUES (?, ?, ?, ?, ?)', (uid, 100000.0, 0.0, 0.0, 100000.0))
    conn.commit()
    cur.execute('SELECT id, available_balance FROM paper_wallet WHERE user_id=?', (uid,))
    w=cur.fetchone()
wid, avail = w
print('Wallet', wid, 'available', avail)
# check for open trade
cur.execute("SELECT id, side FROM paper_trades WHERE user_id=? AND config_id IS NOT NULL AND status='OPEN'", (uid,))
open_t = cur.fetchone()
if open_t:
    print('Found existing open trade', open_t)
else:
    # create trade with margin 5000, leverage 40, entry_price 1000
    margin=5000.0; leverage=40; entry_price=1000.0
    if (avail or 0.0) < margin:
        print('Insufficient available balance')
    else:
        qty = (margin * leverage)/entry_price
        entry_time = datetime.utcnow().isoformat()
        cur.execute('INSERT INTO paper_trades (user_id, config_id, symbol, tv_symbol, side, qty, entry_price, entry_time, pnl_inr, status, strategy, margin, leverage, locked_amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (uid, None, 'ETHUSDT', None, 'BUY', qty, entry_price, entry_time, 0.0, 'OPEN', 'standalone-test', margin, leverage, margin))
        conn.commit()
        tid = cur.lastrowid
        print('Inserted trade id', tid, 'qty', qty)
        # deduct wallet
        new_avail = (avail or 0.0) - margin
        cur.execute('UPDATE paper_wallet SET available_balance=? WHERE id=?', (new_avail, wid))
        conn.commit()
        print('Wallet updated', wid, 'available', new_avail)

# print last trades
print('\nLast trades:')
for r in cur.execute('SELECT id, user_id, symbol, side, qty, entry_price, margin, leverage, locked_amount, status FROM paper_trades ORDER BY id DESC LIMIT 5'):
    print(r)
# print wallet
print('\nWallet row:')
for r in cur.execute('SELECT id, user_id, balance, available_balance FROM paper_wallet WHERE user_id=?', (uid,)):
    print(r)
conn.close()

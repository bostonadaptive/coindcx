import sqlite3, os
from datetime import datetime
DB=os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'instance', 'coindcx.db'))
print('DB:', DB)
conn=sqlite3.connect(DB)
cur=conn.cursor()

# Parameters for the forced trade
user_email = 'test_paper@example.com'
symbol = 'ETHUSDT'
side = 'BUY'
entry_price = 1000.0
margin = 5000.0
leverage = 40
qty = (margin * leverage) / entry_price
locked_amount = margin
status = 'OPEN'
strategy = 'test-strategy'
entry_time = datetime.utcnow().isoformat()

# find user id
cur.execute("SELECT id FROM users WHERE email=?", (user_email,))
row = cur.fetchone()
if not row:
    print('User not found:', user_email)
else:
    uid = row[0]
    print('Found user id', uid)
    # insert trade
    cur.execute('''INSERT INTO paper_trades (user_id, config_id, symbol, tv_symbol, side, qty, entry_price, entry_time, exit_price, exit_time, pnl_inr, status, strategy, margin, leverage, locked_amount)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (uid, None, symbol, None, side, qty, entry_price, entry_time, None, None, 0.0, status, strategy, margin, leverage, locked_amount))
    conn.commit()
    tid = cur.lastrowid
    print('Inserted paper_trade id', tid)
    # update wallet available_balance
    cur.execute('SELECT id, balance, available_balance FROM paper_wallet WHERE user_id=?', (uid,))
    w = cur.fetchone()
    if w:
        wid, bal, avail = w
        new_avail = (avail or 0.0) - locked_amount
        cur.execute('UPDATE paper_wallet SET available_balance=? WHERE id=?', (new_avail, wid))
        conn.commit()
        print('Updated wallet id', wid, 'available:', avail, '->', new_avail)
    else:
        print('No paper_wallet found for user; creating one and deducting')
        bal = 100000.0
        new_avail = bal - locked_amount
        cur.execute('INSERT INTO paper_wallet (user_id, balance, realized_pnl, unrealized_pnl, available_balance) VALUES (?, ?, ?, ?, ?)', (uid, bal, 0.0, 0.0, new_avail))
        conn.commit()
        print('Created wallet with available:', new_avail)

# print last 3 paper_trades and wallet for user
print('\nLast 3 paper_trades:')
for r in cur.execute('SELECT id, user_id, symbol, side, qty, entry_price, margin, leverage, locked_amount, status FROM paper_trades ORDER BY id DESC LIMIT 3'):
    print(r)

print('\nWallet record:')
for r in cur.execute("SELECT pw.id, pw.user_id, pw.balance, pw.available_balance, pw.realized_pnl, pw.unrealized_pnl, u.email FROM paper_wallet pw LEFT JOIN users u ON u.id = pw.user_id WHERE u.email=?", (user_email,)):
    print(r)

conn.close()

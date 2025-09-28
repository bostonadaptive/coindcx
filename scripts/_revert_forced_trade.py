import sqlite3, os
DB=os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'instance', 'coindcx.db'))
conn=sqlite3.connect(DB)
cur=conn.cursor()
# delete forced trade id 1 if exists
cur.execute('SELECT id, user_id, margin FROM paper_trades WHERE id=?', (1,))
r=cur.fetchone()
if r:
    tid, uid, margin = r
    print('Deleting trade id', tid, 'user', uid, 'margin', margin)
    cur.execute('DELETE FROM paper_trades WHERE id=?', (tid,))
    # restore wallet available_balance
    cur.execute('SELECT id, available_balance FROM paper_wallet WHERE user_id=?', (uid,))
    w = cur.fetchone()
    if w:
        wid, avail = w
        new_avail = (avail or 0.0) + (margin or 0.0)
        print('Restoring wallet id', wid, 'available', avail, '->', new_avail)
        cur.execute('UPDATE paper_wallet SET available_balance=? WHERE id=?', (new_avail, wid))
    conn.commit()
else:
    print('Forced trade id 1 not found')

# show remaining paper_trades
print('\nRemaining paper_trades')
for r in cur.execute('SELECT id, user_id, symbol, side, qty, entry_price, margin, locked_amount, status FROM paper_trades ORDER BY id'):
    print(r)
# show wallet
print('\nWallets:')
for r in cur.execute('SELECT pw.id, pw.user_id, pw.balance, pw.available_balance, u.email FROM paper_wallet pw LEFT JOIN users u ON u.id=pw.user_id WHERE u.email="test_paper@example.com"'):
    print(r)
conn.close()

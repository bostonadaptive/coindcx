import sqlite3, os
DB=os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'instance', 'coindcx.db'))
conn=sqlite3.connect(DB)
cur=conn.cursor()
print('DB:', DB)
print('\nLast 5 paper_trades:')
for r in cur.execute('SELECT id, user_id, symbol, side, qty, entry_price, margin, leverage, locked_amount, status FROM paper_trades ORDER BY id DESC LIMIT 5'):
    print(r)
print('\nPaper wallets for test user:')
for r in cur.execute("SELECT pw.id, pw.user_id, pw.balance, pw.available_balance, pw.realized_pnl, pw.unrealized_pnl, u.email FROM paper_wallet pw LEFT JOIN users u ON u.id = pw.user_id WHERE u.email='test_paper@example.com'"):
    print(r)
conn.close()

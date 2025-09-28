import sqlite3, os
DB=os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'instance', 'coindcx.db'))
con=sqlite3.connect(DB)
cur=con.cursor()
for row in cur.execute('SELECT id, user_id, config_id, symbol, status, exit_reason FROM paper_trades ORDER BY id DESC LIMIT 20'):
    print(row)
con.close()

import sqlite3, os
DB=os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'instance', 'coindcx.db'))
con=sqlite3.connect(DB)
cur=con.cursor()
cur.execute('UPDATE paper_trades SET exit_reason = ? WHERE id = ?', ('Inserted test reason', 1))
con.commit()
cur.execute('SELECT id, exit_reason FROM paper_trades WHERE id = 1')
print(cur.fetchone())
con.close()

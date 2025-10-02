import sqlite3, json, os
p='instance/coindcx.db'
print('DB exists:', os.path.exists(p), p)
if not os.path.exists(p):
    raise SystemExit(1)
con=sqlite3.connect(p)
cur=con.cursor()
cur.execute("PRAGMA table_info('paper_trades')")
cols=cur.fetchall()
print(json.dumps(cols, default=str, indent=2))

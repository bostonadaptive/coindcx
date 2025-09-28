import sqlite3
p='d:/Backup/My Projects/CoinDCX/webApp/instance/coindcx.db'
con=sqlite3.connect(p)
for t in ('users','credentials','user_strategy_setup'):
    print('----',t)
    cur=con.execute(f"PRAGMA table_info('{t}')")
    for r in cur.fetchall():
        print(r)
con.close()

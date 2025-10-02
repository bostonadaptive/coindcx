import sqlite3, os
p=os.path.abspath('coindcx.db')
print('DB:',p)
con=sqlite3.connect(p)
try:
    con.execute('CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id);')
    con.commit()
    print('Created idx_watchlist_user')
except Exception as e:
    print('ERROR',e)
finally:
    con.close()
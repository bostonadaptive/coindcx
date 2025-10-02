#!/usr/bin/env python3
import sqlite3
DB='instance/coindcx.db'
conn=sqlite3.connect(DB)
cur=conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables=[r[0] for r in cur.fetchall()]
results=[]
for t in tables:
    cur.execute(f"PRAGMA table_info('{t}')")
    cols=[r[1] for r in cur.fetchall() if r[2].upper().startswith('TEXT') or 'CHAR' in r[2].upper() or 'CLOB' in r[2].upper()]
    for c in cols:
        q=f"SELECT rowid, {c} FROM {t} WHERE {c} LIKE '%BINANCE:%'"
        try:
            cur.execute(q)
            rows=cur.fetchall()
            for row in rows:
                results.append((t,c,row[0],row[1]))
        except Exception:
            pass

print('Found occurrences:')
for r in results:
    print(r)
print('Done')
conn.close()

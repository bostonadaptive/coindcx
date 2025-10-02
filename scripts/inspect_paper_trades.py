#!/usr/bin/env python3
import sqlite3
from pprint import pprint

DB='instance/coindcx.db'
conn=sqlite3.connect(DB)
cur=conn.cursor()
cur.execute('SELECT id, symbol, qty, margin, leverage, entry_price FROM paper_trades ORDER BY id')
rows=cur.fetchall()
print(f"Loaded {len(rows)} rows from {DB}")
for r in rows:
    id,sym,qty,margin,lev,ep=r
    print(f"id={id:3} symbol={sym:20} qty={qty:0.6f} margin={margin} lev={lev} entry_price={ep}")
conn.close()

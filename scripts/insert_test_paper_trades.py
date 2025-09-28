#!/usr/bin/env python3
"""
Insert test paper trades safely into instance/coindcx.db
- Creates a backup copy before modifying
- Inserts 2 OPEN trades for XRPUSDT and SOLUSDT
- Inserts 5 CLOSED trades with random data
- Updates paper_wallet.available_balance to reflect locked margins

Usage: python scripts/insert_test_paper_trades.py
"""
import shutil
import sqlite3
import os
import time
import random
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(__file__))
DB = os.path.join(BASE, 'instance', 'coindcx.db')
BACKUP = DB + f'.bak_insert_test_{int(time.time())}'

print('DB:', DB)
if not os.path.exists(DB):
    raise SystemExit('Database not found at ' + DB)

print('Creating backup ->', BACKUP)
shutil.copy2(DB, BACKUP)

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# pick a user to attach trades to: prefer a test user email if present
cur.execute("SELECT id, email FROM users WHERE email LIKE '%test%' LIMIT 1")
row = cur.fetchone()
if row:
    user_id = row['id']
else:
    # fallback: pick any user
    cur.execute('SELECT id, email FROM users LIMIT 1')
    row = cur.fetchone()
    if not row:
        raise SystemExit('No users found in DB to attach trades to')
    user_id = row['id']

print('Using user id', user_id, 'email=', row['email'])

# ensure paper_wallet exists
cur.execute('SELECT id, available_balance FROM paper_wallet WHERE user_id=?', (user_id,))
w = cur.fetchone()
if not w:
    print('No paper_wallet found for user, creating one with default 100000')
    cur.execute('INSERT INTO paper_wallet (user_id, balance, realized_pnl, unrealized_pnl, available_balance) VALUES (?,?,?,?,?)', (user_id, 100000.0, 0.0, 0.0, 100000.0))
    conn.commit()
    cur.execute('SELECT id, available_balance FROM paper_wallet WHERE user_id=?', (user_id,))
    w = cur.fetchone()

wallet_id = w['id']
avail_before = float(w['available_balance'] or 0.0)
print('Wallet id', wallet_id, 'available before', avail_before)

now = datetime.utcnow()

# helper to insert a trade
def insert_trade(symbol, side, qty, entry_price, margin, leverage, status='OPEN', entry_time=None, exit_price=None, exit_time=None):
    et = entry_time or now
    cur.execute('''
        INSERT INTO paper_trades (user_id, config_id, symbol, tv_symbol, side, qty, entry_price, entry_time, exit_price, exit_time, margin, leverage, locked_amount, pnl_inr, status, strategy)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        user_id, None, symbol, None, side, qty, entry_price, et.isoformat(), exit_price, exit_time and exit_time.isoformat() or None, margin, leverage, margin if status=='OPEN' else 0.0, 0.0, status, 'test_strategy'
    ))
    return cur.lastrowid

# Insert 2 OPEN positions
open_trades = [
    ('XRPUSDT', 'BUY'),
    ('SOLUSDT', 'BUY')
]

locked_total = 0.0
for sym, side in open_trades:
    price = round(random.uniform(0.3, 1.5), 4) if sym.startswith('XRP') else round(random.uniform(15, 50), 4)
    leverage = random.choice([1, 2, 5, 10])
    margin = round(random.uniform(1000, 5000), 2)
    qty = round((margin * leverage) / max(price, 0.0001), 6)
    tid = insert_trade(sym, side, qty, price, margin, leverage, status='OPEN')
    print('Inserted OPEN trade id', tid, sym, 'qty', qty, 'entry', price, 'margin', margin, 'lev', leverage)
    locked_total += margin

# Insert 5 CLOSED trades with random data
closed_symbols = ['BTCUSDT','ETHUSDT','ADAUSDT','DOGEUSDT','MATICUSDT']
for i in range(5):
    sym = closed_symbols[i % len(closed_symbols)]
    side = random.choice(['BUY','SELL'])
    entry_price = round(random.uniform(10, 60000), 2)
    exit_price = round(entry_price * random.uniform(0.95, 1.1), 2)
    leverage = random.choice([1,2,3,5,10])
    margin = round(random.uniform(500, 10000), 2)
    qty = round((margin * leverage) / max(entry_price, 0.0001), 6)
    entry_time = now - timedelta(days=random.randint(1,30), hours=random.randint(0,23))
    exit_time = entry_time + timedelta(hours=random.randint(1,72))
    tid = insert_trade(sym, side, qty, entry_price, margin, leverage, status='CLOSED', entry_time=entry_time, exit_price=exit_price, exit_time=exit_time)
    print('Inserted CLOSED trade id', tid, sym, 'entry', entry_price, 'exit', exit_price, 'qty', qty)

# Update wallet available balance: deduct locked_total
new_avail = max(0.0, avail_before - locked_total)
cur.execute('UPDATE paper_wallet SET available_balance=? WHERE id=?', (new_avail, wallet_id))
print('Adjusted wallet available from', avail_before, '->', new_avail, 'locked_total', locked_total)

conn.commit()

# Print last 10 paper_trades
cur.execute('SELECT id, symbol, side, qty, entry_price, margin, leverage, status FROM paper_trades ORDER BY id DESC LIMIT 10')
for r in cur.fetchall():
    print(dict(r))

cur.execute('SELECT id, user_id, balance, available_balance FROM paper_wallet WHERE user_id=?', (user_id,))
print('Wallet now:', dict(cur.fetchone()))

conn.close()
print('Done. Backup stored at', BACKUP)

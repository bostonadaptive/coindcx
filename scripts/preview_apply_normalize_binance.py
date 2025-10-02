#!/usr/bin/env python3
"""
Preview and optionally normalize symbols that use the 'BINANCE:' tv prefix into CoinDCX format 'B-<BASE>_QUOTE'
This script will print proposed changes and, if --apply is passed, update them in-place.

It handles a whitelist of tables/columns discovered earlier. Use --apply only after reviewing the preview. Backups are recommended.
"""
import sqlite3, argparse, re

TABLE_COLS = [
    ('strategy_signals','symbol'),
    ('watchlist','symbol'),
    ('user_strategy_setup','symbol'),
    ('backtest_configs','symbol_tv'),
    ('paper_trades','symbol'),
]


def binance_to_coindcx(tv):
    # e.g. 'BINANCE:ETHUSDT' -> 'B-ETH_USDT'
    if not tv or not tv.startswith('BINANCE:'):
        return tv
    s = tv.split(':',1)[1]
    # naive split: BASE + QUOTE
    # handle symbols like SOLUSDT -> SOL_USDT
    m = re.match(r'^([A-Z]+)(USDT|BTC|INR|USD)$', s)
    if m:
        base = m.group(1)
        quote = m.group(2)
        return f'B-{base}_{quote}'
    # fallback: replace ':' and '/' and return
    return 'B-' + s.replace('/','_')

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--apply',action='store_true')
    args=p.parse_args()

    DB='instance/coindcx.db'
    conn=sqlite3.connect(DB)
    cur=conn.cursor()

    changes=[]
    for t,c in TABLE_COLS:
        try:
            cur.execute(f"SELECT rowid, {c} FROM {t} WHERE {c} LIKE '%BINANCE:%'")
            rows=cur.fetchall()
            for row in rows:
                rid,val=row
                new=binance_to_coindcx(val)
                if new!=val:
                    changes.append((t,c,rid,val,new))
        except Exception as e:
            print('skip',t,c,e)

    if not changes:
        print('No BINANCE: occurrences found to normalize')
        conn.close()
        exit(0)

    print('Proposed changes:')
    for ch in changes:
        print(ch)

    if not args.apply:
        print('\nRun with --apply to update these rows in the DB (make sure you have a backup).')
        conn.close()
        exit(0)

    print('\nApplying changes...')
    updated=0
    for t,c,rid,old,new in changes:
        q=f"UPDATE {t} SET {c} = ? WHERE rowid = ?"
        cur.execute(q,(new,rid))
        updated+=1
    conn.commit()
    print(f'Updated {updated} rows')
    conn.close()

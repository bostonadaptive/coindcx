import sqlite3
import os
p=os.path.join(os.path.dirname(__file__), '..', 'coindcx.db')
print('DB path:', p)
if not os.path.exists(p):
    print('Database file not found')
    raise SystemExit(1)
con=sqlite3.connect(p)
c=con.cursor()
tables=['paper_trades','user_strategy_setup','strategy_signals','watchlist','credentials']
for t in tables:
    print('\nTABLE',t)
    try:
        rows=list(c.execute(f"PRAGMA index_list('{t}')"))
        if not rows:
            print('  (no indexes)')
            continue
        for row in rows:
            print(' ',row)
            idx_name=row[1]
            info=list(c.execute(f"PRAGMA index_info('{idx_name}')"))
            for info_row in info:
                print('    ',info_row)
    except Exception as e:
        print('  ERROR',e)
con.close()

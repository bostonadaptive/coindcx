import sqlite3, os
roots = [os.path.abspath('coindcx.db'), os.path.abspath(os.path.join('instance','coindcx.db'))]
for p in roots:
    print('\nDB:', p)
    if not os.path.exists(p):
        print('  (not found)')
        continue
    con=sqlite3.connect(p)
    try:
        rows = list(con.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','index') ORDER BY type, name"))
        if not rows:
            print('  (no tables/indexes)')
        for r in rows[:50]:
            print(' ', r)
    finally:
        con.close()
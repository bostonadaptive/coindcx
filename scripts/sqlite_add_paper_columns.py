import sqlite3
import shutil
import os

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'instance', 'coindcx.db'))

def backup_db(path: str):
    bak = path + '.bak_paper_cols'
    shutil.copy2(path, bak)
    print('Backup created at', bak)

def add_column_if_missing(conn, table, column_def):
    cur = conn.cursor()
    colname = column_def.split()[0]
    cur.execute("PRAGMA table_info(%s)" % table)
    cols = [r[1] for r in cur.fetchall()]
    if colname in cols:
        print(f"Column {colname} already exists on {table}")
        return
    sql = f"ALTER TABLE {table} ADD COLUMN {column_def}"
    print('Running:', sql)
    cur.execute(sql)
    conn.commit()

def main():
    if not os.path.exists(DB_PATH):
        print('DB not found at', DB_PATH)
        return
    backup_db(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    try:
        add_column_if_missing(conn, 'paper_trades', 'margin FLOAT DEFAULT 0.0')
        add_column_if_missing(conn, 'paper_trades', 'leverage INTEGER DEFAULT 1')
        add_column_if_missing(conn, 'paper_trades', 'locked_amount FLOAT DEFAULT 0.0')
        print('Done')
    finally:
        conn.close()

if __name__ == '__main__':
    main()

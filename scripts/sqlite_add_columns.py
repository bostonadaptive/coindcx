"""Safe SQLite alter helper: adds missing columns to existing tables.

Usage (PowerShell):
    python scripts\sqlite_add_columns.py --db instance\coindcx.db

This script backs up the DB (copies to .bak) before applying changes.
"""
import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

CHANGES = [
    {
        'table': 'users',
        'column': 'currency',
        'type': "VARCHAR(10)",
        'default': "'INR'"
    },
    {
        'table': 'credentials',
        'column': 'currency',
        'type': "VARCHAR(10)",
        'default': "NULL"
    },
    {
        'table': 'user_strategy_setup',
        'column': 'is_paper',
        'type': "INTEGER",
        'default': '0'
    }
]


def column_exists(conn, table, column):
    cur = conn.execute(f"PRAGMA table_info('{table}')")
    cols = [r[1] for r in cur.fetchall()]
    return column in cols


def add_column(conn, table, column, ctype, default):
    sql = f"ALTER TABLE {table} ADD COLUMN {column} {ctype} DEFAULT {default};"
    print('Running:', sql)
    conn.execute(sql)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', required=True, help='Path to sqlite DB file')
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print('DB not found:', db_path)
        sys.exit(2)

    backup = db_path.with_suffix(db_path.suffix + '.bak')
    print('Backing up', db_path, 'to', backup)
    shutil.copy2(db_path, backup)

    conn = sqlite3.connect(str(db_path))
    try:
        for ch in CHANGES:
            table = ch['table']
            col = ch['column']
            if column_exists(conn, table, col):
                print(f"Skipping {table}.{col}, already exists")
                continue
            add_column(conn, table, col, ch['type'], ch['default'])
        conn.commit()
        print('Done. Commit successful.')
    except Exception as e:
        print('Error during migration:', e)
        print('Restoring backup...')
        conn.rollback()
        conn.close()
        shutil.copy2(backup, db_path)
        print('Backup restored')
        sys.exit(1)
    finally:
        conn.close()

if __name__ == '__main__':
    main()

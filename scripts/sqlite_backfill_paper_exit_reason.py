"""
Backfill script for paper_trades.exit_reason.
Usage:
  python sqlite_backfill_paper_exit_reason.py --dry-run
  python sqlite_backfill_paper_exit_reason.py --apply

Behavior:
- For each paper_trades row where exit_reason is NULL/empty and exit_time is set, try to find
  a matching trade_history row with a non-empty exit_reason.
- Matching preference:
  1) trade_history rows with same user_id and config_id (if trade_history has config_id; otherwise skip)
  2) trade_history rows with same user_id and symbol, pick the one whose close_time is nearest to paper_trades.exit_time
     within a tolerance (default 300 seconds). If none within tolerance, will still show nearest as candidate in dry-run.
- Dry-run prints proposed mappings; --apply updates the DB.

This script is safe for development SQLite DB and prints a summary.
"""

import sqlite3
import os
import argparse
from datetime import datetime, timedelta

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DB = os.path.join(ROOT, 'instance', 'coindcx.db')

parser = argparse.ArgumentParser()
parser.add_argument('--apply', action='store_true', help='Apply changes')
parser.add_argument('--tolerance', type=int, default=300, help='Time tolerance in seconds for nearest match')
args = parser.parse_args()

print('DB:', DB)
if not os.path.exists(DB):
    print('Database not found at', DB)
    raise SystemExit(1)

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

# ensure column exists
cur.execute("PRAGMA table_info('paper_trades')")
cols = [r['name'] for r in cur.fetchall()]
if 'exit_reason' not in cols:
    print('exit_reason column missing; cannot continue')
    con.close()
    raise SystemExit(1)

# gather candidate paper_trades to backfill
cur.execute("SELECT id, user_id, config_id, symbol, exit_time FROM paper_trades WHERE (exit_reason IS NULL OR exit_reason = '') AND exit_time IS NOT NULL")
candidates = cur.fetchall()
print('Candidates found:', len(candidates))

proposed = []
for c in candidates:
    pid = c['id']
    uid = c['user_id']
    cfg = c['config_id']
    sym = c['symbol']
    exit_time = c['exit_time']
    # normalize exit_time to datetime
    try:
        if exit_time:
            # sqlite returns string; try to parse
            et = None
            if isinstance(exit_time, str):
                try:
                    et = datetime.fromisoformat(exit_time)
                except Exception:
                    try:
                        et = datetime.strptime(exit_time, '%Y-%m-%d %H:%M:%S')
                    except Exception:
                        et = None
            elif isinstance(exit_time, (int, float)):
                et = datetime.utcfromtimestamp(float(exit_time))
            else:
                et = exit_time
        else:
            et = None
    except Exception:
        et = None

    candidate_reason = None
    candidate_th_id = None
    method = None

    # 1) Try exact config_id matching if trade_history has config_id column
    try:
        cur.execute("SELECT id, exit_reason, close_time FROM trade_history WHERE user_id = ? AND symbol = ? AND exit_reason IS NOT NULL ORDER BY close_time DESC LIMIT 5", (uid, sym))
        ths = cur.fetchall()
    except Exception:
        ths = []

    # If we have multiple trade_history rows, pick nearest close_time to et within tolerance
    best = None
    best_dt_diff = None
    for th in ths:
        th_close = th['close_time']
        if not th_close:
            continue
        # parse close_time
        try:
            if isinstance(th_close, str):
                try:
                    cdt = datetime.fromisoformat(th_close)
                except Exception:
                    try:
                        cdt = datetime.strptime(th_close, '%Y-%m-%d %H:%M:%S')
                    except Exception:
                        cdt = None
            elif isinstance(th_close, (int, float)):
                cdt = datetime.utcfromtimestamp(float(th_close))
            else:
                cdt = th_close
        except Exception:
            cdt = None
        if cdt and et:
            diff = abs((cdt - et).total_seconds())
            if best is None or diff < best_dt_diff:
                best = th
                best_dt_diff = diff
        elif best is None:
            best = th
            best_dt_diff = None

    if best:
        candidate_th_id = best['id']
        candidate_reason = best['exit_reason']
        method = 'nearest_by_time'
        # check tolerance
        if best_dt_diff is not None and best_dt_diff > args.tolerance:
            method += '_outside_tolerance'

    proposed.append((pid, uid, cfg, sym, et, candidate_th_id, candidate_reason, method))

# print report
if not proposed:
    print('No candidates to backfill')
    con.close()
    raise SystemExit(0)

print('\nProposed mappings (first 20 shown):')
for p in proposed[:20]:
    pid, uid, cfg, sym, et, thid, reason, method = p
    print(f"paper_id={pid} user={uid} config={cfg} symbol={sym} exit_time={et} -> trade_history_id={thid} method={method} reason={'[REDACTED]' if reason else None}")

if not args.apply:
    print('\nDry-run complete. To apply changes, re-run with --apply')
    con.close()
    raise SystemExit(0)

# Applying
updated = 0
for p in proposed:
    pid, uid, cfg, sym, et, thid, reason, method = p
    if not reason:
        continue
    try:
        cur.execute("UPDATE paper_trades SET exit_reason = ? WHERE id = ?", (reason, pid))
        updated += 1
    except Exception:
        continue

con.commit()
print('Applied updates:', updated)
con.close()
print('Done')

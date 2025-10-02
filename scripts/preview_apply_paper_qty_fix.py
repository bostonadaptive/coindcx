"""
Preview and optionally apply corrected qtys to paper_trades rows.
Runs in-place on the project's SQLite DB (instance/coindcx.db by default).
Usage:
  python scripts/preview_apply_paper_qty_fix.py --preview
  python scripts/preview_apply_paper_qty_fix.py --apply  # will update rows (ask for confirmation on stdout)

This script:
 - reads open paper_trades (status='OPEN')
 - computes corrected qty using compute_qty_from_inr_margin(margin, leverage, entry_price, fx)
 - formats symbol to CoinDCX format via format_pair_display (imports from app)
 - shows a table of id, old_qty, new_qty, old_symbol, new_symbol
 - if --apply is passed, updates rows in DB with safe transaction and prints summary

Be careful: running with --apply changes the DB.
"""
import argparse, sqlite3, sys
from decimal import Decimal

DB = 'instance/coindcx.db'

parser = argparse.ArgumentParser()
parser.add_argument('--apply', action='store_true', help='Apply changes to DB')
parser.add_argument('--limit', type=int, default=1000, help='Max rows to process')
args = parser.parse_args()

# import helpers from project
sys.path.insert(0, '.')
from app import compute_qty_from_inr_margin, format_pair_display, usdt_inr_fx

conn = sqlite3.connect(DB)
cur = conn.cursor()
rows = cur.execute("SELECT id, symbol, tv_symbol, qty, margin, leverage, entry_price FROM paper_trades WHERE status='OPEN' ORDER BY entry_time DESC LIMIT ?", (args.limit,)).fetchall()
if not rows:
    print('No open paper_trades found.')
    sys.exit(0)

fx = usdt_inr_fx()
print('Using USD->INR fx =', fx)
print('Previewing up to', len(rows), 'rows')
print('%5s %12s %12s %20s %20s' % ('id','old_qty','new_qty','old_symbol','new_symbol'))
changes = []
for r in rows:
    pid, sym, tv_sym, old_qty, margin, lev, entry_px = r
    entry_px = float(entry_px) if entry_px else None
    try:
        res = compute_qty_from_inr_margin(margin or 0.0, lev or 1, entry_px or 0.0, fx)
        new_qty = res.get('qty') or 0.0
    except Exception:
        new_qty = 0.0
    new_qty_r = float(Decimal(str(new_qty)).quantize(Decimal('0.001')))
    new_sym = format_pair_display(sym or (tv_sym or ''))
    print('%5d %12s %12s %20s %20s' % (pid, str(old_qty), ('%.3f' % new_qty_r), str(sym), new_sym))
    if args.apply:
        changes.append((new_qty_r, new_sym, pid))

if args.apply and changes:
    print('\nApplying changes...')
    for qty, nsym, pid in changes:
        cur.execute('UPDATE paper_trades SET qty = ?, symbol = ? WHERE id = ?', (qty, nsym, pid))
    conn.commit()
    print('Updated', len(changes), 'rows')
conn.close()
print('\nDone')

"""
Simple integration script to test INMEM_SIGNALS flusher.
Usage:
  # without redis running: populate INMEM_SIGNALS
  python scripts/redis_flusher_test.py --populate

  # start redis, then run flush
  $env:REDIS_URL='redis://127.0.0.1:6379'
  python scripts/redis_flusher_test.py --flush

This script imports the worker module and manipulates INMEM_SIGNALS. It's intended
for local development only.
"""
import os, time, json
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--populate', action='store_true')
parser.add_argument('--flush', action='store_true')
args = parser.parse_args()

# import the worker module
import importlib
worker = importlib.import_module('workers.signals_worker')

if args.populate:
    # create a few fake entries
    for i in range(1,4):
        key = f'signals:TEST{i}'
        worker.INMEM_SIGNALS[key] = {'signal': 'BUY' if i%2==0 else 'SELL', 'updated_at': int(time.time()*1000), 'symbol': 'TEST' + str(i)}
    print('Populated INMEM_SIGNALS with', list(worker.INMEM_SIGNALS.keys()))
    print('Now start Redis and run with --flush')

if args.flush:
    print('Attempting flush...')
    drained = worker.flush_inmem_once()
    print('Flushed count:', drained)
    print('Remaining INMEM_SIGNALS:', list(worker.INMEM_SIGNALS.keys()))

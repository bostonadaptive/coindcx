import importlib, sys, traceback
from pathlib import Path

# Ensure project root (one level up from scripts/) is on sys.path so
# importing top-level modules like `app` works regardless of current
# working directory or where this script is executed from.
repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

try:
    m = importlib.import_module('app')
    print('IMPORT_APP_OK', getattr(m, '__name__', 'unknown'))
except Exception:
    print('IMPORT_APP_ERR')
    traceback.print_exc()
    sys.exit(1)

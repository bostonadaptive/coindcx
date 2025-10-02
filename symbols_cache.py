import os
import json
from typing import List, Dict, Any

SYMBOLS_JSON_PATH = os.path.join(os.path.dirname(__file__), 'active_symbols.json')


def fetch_and_cache_symbols(fetch_fn) -> List[Dict[str, Any]]:
    """
    Fetch symbols using the provided fetch_fn if cache is missing, else load from cache.
    fetch_fn should return a list of symbol dicts.
    """
    if os.path.exists(SYMBOLS_JSON_PATH):
        with open(SYMBOLS_JSON_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    symbols = fetch_fn()
    with open(SYMBOLS_JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(symbols, f, ensure_ascii=False, indent=2)
    return symbols


def get_cached_symbols() -> List[Dict[str, Any]]:
    """Load symbols from cache if available."""
    if os.path.exists(SYMBOLS_JSON_PATH):
        with open(SYMBOLS_JSON_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

# Example usage:
# from _tsl_logic import active_instruments
# symbols = fetch_and_cache_symbols(lambda: active_instruments('isolated'))
# cached = get_cached_symbols()

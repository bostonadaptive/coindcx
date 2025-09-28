"""Background worker that periodically fetches MCP endpoints and caches results.

- Calls MCP endpoints via `mcp_client`.
- Writes cached JSON into Redis (if configured) and `MCPCache` DB table for persistence.
- Starts as a daemon thread when requested by the Flask app.
"""
import threading, time, json, traceback, os
from datetime import datetime
from typing import List

from mcp_client import mcp_get, mcp_post
from model import db, MCPCache

_redis_url = os.environ.get('REDIS_URL') or os.environ.get('REDIS_URI')
_redis = None
if _redis_url:
    try:
        import redis as _redis_mod
        _redis = _redis_mod.from_url(_redis_url, decode_responses=True)
    except Exception:
        _redis = None

# endpoints to poll periodically (relative paths on the MCP proxy)
POLL_ENDPOINTS: List[str] = os.environ.get('MCP_POLL_ENDPOINTS', '/exchange/v1/derivatives/futures/data/active_instruments,/market_data/last_price').split(',')
POLL_INTERVAL = int(os.environ.get('MCP_POLL_INTERVAL', '15'))  # seconds


def _save_to_db(key: str, value: dict):
    try:
        js = json.dumps(value)
        rec = db.session.query(MCPCache).filter_by(key=key).first()
        if rec:
            rec.value_json = js
            rec.updated_at = datetime.utcnow()
        else:
            rec = MCPCache(key=key, value_json=js)
            db.session.add(rec)
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass


def _save_to_redis(key: str, value: dict):
    try:
        if not _redis:
            return
        _redis.set(key, json.dumps(value))
        # set a TTL so cache auto-expires
        _redis.expire(key, max(60, POLL_INTERVAL * 3))
    except Exception:
        pass


def poll_once():
    """Poll all configured endpoints once and cache the responses."""
    for p in POLL_ENDPOINTS:
        p = p.strip()
        if not p:
            continue
        try:
            res = mcp_get(p)
            key = f'mcp:{p}'
            if res is not None:
                _save_to_redis(key, res)
                # try to persist a lightweight DB copy
                try:
                    _save_to_db(key, {'ts': int(time.time()), 'payload': res})
                except Exception:
                    pass
        except Exception:
            traceback.print_exc()


def _worker_loop():
    while True:
        try:
            poll_once()
        except Exception:
            traceback.print_exc()
        time.sleep(POLL_INTERVAL)


def start_mcp_worker():
    t = threading.Thread(target=_worker_loop, daemon=True, name='mcp-worker')
    t.start()
    return t


if __name__ == '__main__':
    start_mcp_worker()
    while True:
        time.sleep(1)

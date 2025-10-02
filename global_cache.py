"""Global fast cache used across the app.

Features:
- In-memory dict for fastest reads.
- Optional Redis backing for cross-process sharing.
- DB persistence via MCPCache already exists (worker writes there).
- Simple API: get(key), set(key, value), keys()
"""
from typing import Any, Dict, Optional, List
import time, json, os

_mem: Dict[str, Dict] = {}

_redis_url = os.environ.get('REDIS_URL') or os.environ.get('REDIS_URI')
_redis = None
if _redis_url:
    try:
        import redis as _redis_mod
        _redis = _redis_mod.from_url(_redis_url, decode_responses=True)
    except Exception:
        _redis = None

def _mem_key(k: str) -> str:
    return f"mcp:{k}"

def set(key: str, value: Any, ttl: Optional[int] = None):
    k = _mem_key(key)
    rec = {'value': value, 'ts': int(time.time())}
    _mem[k] = rec
    # publish to redis if available
    try:
        if _redis:
            _redis.set(k, json.dumps(rec))
            if ttl:
                _redis.expire(k, ttl)
    except Exception:
        pass

def get(key: str) -> Optional[Any]:
    k = _mem_key(key)
    # fast in-memory
    rec = _mem.get(k)
    if rec is not None:
        return rec.get('value')
    # try redis
    try:
        if _redis:
            v = _redis.get(k)
            if v:
                try:
                    parsed = json.loads(v)
                    # populate mem for next time
                    _mem[k] = parsed
                    return parsed.get('value')
                except Exception:
                    return None
    except Exception:
        pass
    return None

def keys() -> List[str]:
    out = [k[len('mcp:'):] for k in list(_mem.keys())]
    try:
        if _redis:
            for k in _redis.keys('mcp:*'):
                if k.startswith('mcp:'):
                    name = k[4:]
                    if name not in out:
                        out.append(name)
    except Exception:
        pass
    return out

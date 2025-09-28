"""Lightweight MCP client helpers.

This module centralizes calls to an MCP proxy (like Lobehub MCP) so the rest of the
app can call mcp_get / mcp_post and the client will cache and return JSON safely.
"""
from typing import Optional, Any, Dict
import os, time, json
import requests

MCP_BASE = os.environ.get('COINDCX_MCP') or os.environ.get('COINDCX_API_BASE') or 'https://lobehub.com/mcp/bksinha4497-coindcx-mcp'

# small default timeout
_TIMEOUT = float(os.environ.get('MCP_TIMEOUT', '10'))


def mcp_get(path: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Optional[Dict]:
    url = MCP_BASE.rstrip('/') + path if path.startswith('/') else MCP_BASE.rstrip('/') + '/' + path
    try:
        r = requests.get(url, params=params or {}, headers=headers or {}, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def mcp_post(path: str, json_body: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Optional[Dict]:
    url = MCP_BASE.rstrip('/') + path if path.startswith('/') else MCP_BASE.rstrip('/') + '/' + path
    try:
        r = requests.post(url, json=json_body or {}, headers=headers or {}, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

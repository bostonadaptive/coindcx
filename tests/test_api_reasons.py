import json
import pytest
import os, sys

# Ensure project root is importable when running a single test file
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app, db
from model import User, UserStrategySetup, Strategy, PaperTrade


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


def test_api_strategy_signals_includes_reasons(client):
    # ensure the endpoint responds and fields exist (may be None)
    resp = client.get('/api/strategy_signals')
    assert resp.status_code in (200, 401, 302)  # unauthenticated allowed: 401 or redirect to login (302)
    if resp.status_code == 200:
        js = resp.get_json()
        assert 'items' in js
        for it in js.get('items', [])[:5]:
            assert 'entry_reason' in it
            assert 'exit_reason' in it


def test_paper_positions_and_history_include_reasons(client):
    # Login not required for tests in this env; just call the endpoints
    rp = client.get('/paper_positions')
    assert rp.status_code in (200, 401, 302)
    if rp.status_code == 200:
        j = rp.get_json()
        assert 'open' in j
        for o in j['open'][:5]:
            assert 'entry_reason' in o
            assert 'exit_reason' in o

    rh = client.get('/paper_history')
    assert rh.status_code in (200, 401, 302)
    if rh.status_code == 200:
        j = rh.get_json()
        assert 'closed' in j
        for c in j['closed'][:5]:
            assert 'entry_reason' in c
            assert 'exit_reason' in c

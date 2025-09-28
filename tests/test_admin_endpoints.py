import pytest
import sys, pathlib
# ensure workspace root is on sys.path so 'app' can be imported when pytest runs
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import app, db
from model import User, Role

@pytest.fixture
def client(tmp_path):
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['WTF_CSRF_ENABLED'] = False
    with app.app_context():
        # app already configured db in app.py; just create tables for testing
        db.create_all()
        # create admin role and user if not present
        role = Role.query.filter_by(name='admin').first()
        if not role:
            role = Role(name='admin', description='Admin')
            db.session.add(role)
            db.session.commit()
        admin = User.query.filter_by(email='admin@example.com').first()
        if not admin:
            admin = User(email='admin@example.com', password='x', role_id=role.id)
            db.session.add(admin)
            db.session.commit()
        admin_id = admin.id
    with app.test_client() as c:
        # log in by setting session user_id
        with c.session_transaction() as sess:
            sess['user_id'] = admin_id
            # mark user as admin by role check using DB query in decorator
        yield c


def test_table_info_and_delete_and_run_query(client):
    from sqlalchemy import text
    with app.app_context():
        # create a test table if it doesn't exist, then clear it and seed rows
        db.session.execute(text('CREATE TABLE IF NOT EXISTS test_items (id INTEGER PRIMARY KEY, name TEXT, value INTEGER)'))
        # ensure deterministic state for test runs
        db.session.execute(text('DELETE FROM test_items'))
        db.session.execute(text("INSERT INTO test_items (name, value) VALUES ('a', 10), ('b', 20), ('c', 30)"))
        db.session.commit()

    # fetch table list
    r = client.get('/admin/list_tables')
    assert r.status_code == 200
    js = r.get_json()
    assert any(x['name']=='test_items' for x in js)

    # table info
    r = client.get('/admin/table_info/test_items')
    assert r.status_code == 200
    info = r.get_json()
    assert any(c['name']=='id' for c in info)

    # run select query
    r = client.post('/admin/db_control/run_query', json={'sql':'SELECT * FROM test_items', 'page':1, 'per_page':10})
    assert r.status_code == 200
    res = r.get_json()
    assert 'columns' in res and 'rows' in res
    assert len(res['rows']) == 3

    # enable advanced mode in session
    with client.session_transaction() as sess:
        sess['db_control_advanced'] = True

    # delete where name='b'
    r = client.post('/admin/db_control/delete_row', json={'table':'test_items', 'column':'name', 'value':'b'})
    assert r.status_code == 200
    jsd = r.get_json()
    assert jsd.get('deleted',0) >= 1

    # verify remaining rows
    r = client.post('/admin/db_control/run_query', json={'sql':'SELECT * FROM test_items ORDER BY id', 'page':1, 'per_page':10})
    res2 = r.get_json()
    names = [r[1] for r in res2['rows']]
    assert 'b' not in names

    # update a row
    r = client.post('/admin/db_control/run_query', json={'sql':"UPDATE test_items SET value = 999 WHERE name = 'a'"})
    assert r.status_code == 200
    r = client.post('/admin/db_control/run_query', json={'sql':'SELECT value FROM test_items WHERE name = "a"', 'page':1, 'per_page':10})
    res3 = r.get_json()
    assert res3['rows'][0][0] == 999

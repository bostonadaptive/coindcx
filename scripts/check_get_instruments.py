import requests

BASE='http://127.0.0.1:5000'
EMAIL='test@example.com'
PASSWORD='password123'

s = requests.Session()
print('Logging in...')
r = s.post(BASE + '/login', data={'email':EMAIL,'password':PASSWORD}, allow_redirects=True)
print('login status', r.status_code)
print('session cookies:', s.cookies.get_dict())

r2 = s.get(BASE + '/get_instruments')
print('/get_instruments status', r2.status_code)
text = r2.text
print('response startswith:', text[:200])
try:
    js = r2.json()
    print('json type:', type(js), 'len(if list):', len(js) if isinstance(js, list) else 'obj')
    if isinstance(js, dict) and js.get('error'):
        print('error:', js.get('error'))
except Exception as e:
    print('json parse failed:', e)

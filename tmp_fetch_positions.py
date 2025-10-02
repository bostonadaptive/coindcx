import requests
s = requests.Session()
base = 'http://127.0.0.1:5000'
# create a temp user
r = s.post(base + '/signup', data={'email':'tempuser@example.com','password':'password123'})
print('signup status', r.status_code)
# login
r = s.post(base + '/login', data={'email':'tempuser@example.com','password':'password123'})
print('login status', r.status_code)
# fetch paper_positions
r = s.get(base + '/paper_positions')
print('positions status', r.status_code)
try:
    print(r.json())
except Exception:
    print(r.text[:1000])

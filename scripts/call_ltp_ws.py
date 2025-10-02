import requests
print(requests.get('http://127.0.0.1:5000/ltp_ws?label=BETHUSDT&wait=0.3').text)

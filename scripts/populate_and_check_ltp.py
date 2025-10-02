import requests
print('GET /ltp ->', requests.get('http://127.0.0.1:5000/ltp?label=B-ETH_USDT').text)
print('GET /ltp (short) ->', requests.get('http://127.0.0.1:5000/ltp?label=BETHUSDT').text)
print('then /ltp_ws ->', requests.get('http://127.0.0.1:5000/ltp_ws?label=BETHUSDT&wait=0.3').text)

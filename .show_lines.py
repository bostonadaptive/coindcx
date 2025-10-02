P = 'd:/Backup/My Projects/CoinDCX/webApp/asgi.py'
RANGES = [(1308,1318),(1328,1356),(1388,1398),(1478,1492)]
with open(P, encoding='utf-8') as f:
    for i, l in enumerate(f, start=1):
        for a,b in RANGES:
            if a <= i <= b:
                print(f"{i:4d}: {l.rstrip()}")

import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from technical_strategies import twin_range_filter_strategy
import pandas as pd

# Build synthetic data: initial downtrend then uptrend to force reversal
n_down = 120
n_up = 200
base = 30000.0
# decreasing part
down = [base - i*0.5 for i in range(n_down)]
# increasing part
up = [down[-1] + i*0.7 for i in range(1, n_up+1)]
closes = down + up

df = pd.DataFrame({
    'open': closes,
    'high': [c + 1.0 for c in closes],
    'low': [c - 1.0 for c in closes],
    'close': closes,
})

out = twin_range_filter_strategy(df)

# print the last several rows with signals
print('index, close, buy, sell')
for i in range(len(out)-10, len(out)):
    r = out.iloc[i]
    print(i, r['close'], bool(r['buy_signal']), bool(r['sell_signal']))

print('Final signals:', bool(out.iloc[-1]['buy_signal']), bool(out.iloc[-1]['sell_signal']))

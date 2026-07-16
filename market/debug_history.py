
from market.historical_data import HistoricalDataProvider
from pprint import pprint

candles = HistoricalDataProvider().get_candles()

print("Total candles:", len(candles))

print("\nFirst Candle")
pprint(candles[0])

print("\nLast Candle")
pprint(candles[-1])

print("\nLast 10 Times")

for c in candles[-10:]:
    print(c["time"])
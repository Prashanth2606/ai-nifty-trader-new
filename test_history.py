from market.historical_data import HistoricalDataProvider

provider = HistoricalDataProvider()

candles5 = provider.get_5min_candles()
candles1 = provider.get_1min_candles()

print("5 Minute Candles :", len(candles5))
print("1 Minute Candles :", len(candles1))

print("\nLast 5-Min Candle")
print(candles5[-1])

print("\nLast 1-Min Candle")
print(candles1[-1])
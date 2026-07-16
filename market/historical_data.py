from broker.dhan_client import get_dhan_client, call_with_retry
from datetime import datetime, timedelta


class HistoricalDataProvider:

    def __init__(self):
        self.dhan = get_dhan_client()

    def get_candles(self, interval=5, days=5):

        today = datetime.today()

        from_date = (
            today - timedelta(days=days)
        ).strftime("%Y-%m-%d")

        to_date = today.strftime("%Y-%m-%d")

        response = call_with_retry(

            self.dhan.intraday_minute_data,

            security_id=13,

            exchange_segment="IDX_I",

            instrument_type="INDEX",

            interval=interval,

            from_date=from_date,

            to_date=to_date

        )

        if response["status"] != "success":
            raise Exception(f"Historical Data Error : {response}")

        data = response["data"]

        candles = []

        for i in range(len(data["close"])):

            candles.append({

                "time": data["timestamp"][i],

                "open": data["open"][i],

                "high": data["high"][i],

                "low": data["low"][i],

                "close": data["close"][i],

                "volume": data["volume"][i]

            })

        return candles

    def get_5min_candles(self):

        return self.get_candles(
            interval=5,
            days=5
        )

    def get_1min_candles(self):

        return self.get_candles(
            interval=1,
            days=5
        )
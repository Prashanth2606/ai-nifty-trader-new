from broker.dhan_client import get_dhan_client
from config import EXCHANGE, NIFTY_SECURITY_ID, EXPIRY


class MarketDataProvider:

    def __init__(self):
        self.dhan = get_dhan_client()

    def get_snapshot(self):

        chain = self.dhan.option_chain(
            under_security_id=NIFTY_SECURITY_ID,
            under_exchange_segment=EXCHANGE,
            expiry=EXPIRY
        )

        print("TYPE:", type(chain))
        print("RESPONSE:")
        print(chain)

        return None
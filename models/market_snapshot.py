
from dataclasses import dataclass


@dataclass
class MarketSnapshot:
    spot: float
    atm: float
    option_chain: dict
    candles: list
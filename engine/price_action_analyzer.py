
import pandas as pd


class PriceActionAnalyzer:
    """
    Detects market phase using 1-minute candles.
    """

    def analyze(self, candles):

        df = pd.DataFrame(candles)

        closes = df["close"].tolist()
        highs = df["high"].tolist()
        lows = df["low"].tolist()

        if len(closes) < 10:
            return {
                "phase": "UNKNOWN",
                "move": 0.0,
                "entry_quality": "LOW",
                "is_breakout": False,
                "breakout_direction": None,
                "is_pullback": False,
                "is_exhausted": False
            }

        last = closes[-1]

        previous5 = closes[-6]

        move = last - previous5

        phase = "SIDEWAYS"

        breakout = False
        breakout_direction = None
        pullback = False
        exhausted = False

        # -----------------------
        # Early Uptrend
        # -----------------------

        if move > 20:

            phase = "EARLY_UPTREND"

        elif move < -20:

            phase = "EARLY_DOWNTREND"

        # -----------------------
        # Breakout
        # -----------------------

        recent_high = max(highs[-6:-1])

        recent_low = min(lows[-6:-1])

        if last > recent_high:

            breakout = True
            breakout_direction = "UP"

        if last < recent_low:

            breakout = True
            breakout_direction = "DOWN"

        # -----------------------
        # Pullback
        # -----------------------

        if closes[-1] > closes[-2] > closes[-3]:

            pullback = True

        # -----------------------
        # Exhaustion
        # -----------------------

        if abs(move) > 45:

            exhausted = True

        quality = "MEDIUM"

        if breakout and not exhausted:

            quality = "HIGH"

        elif exhausted:

            quality = "LOW"

        return {

            "phase": phase,

            "move": round(move,2),

            "is_breakout": breakout,

            "breakout_direction": breakout_direction,

            "is_pullback": pullback,

            "is_exhausted": exhausted,

            "entry_quality": quality

        }

import pandas as pd


class PriceActionAnalyzer:
    """
    Detects market phase using 1-minute candles.

    Uses two lookback windows, not one: a short 5-candle (~5 min) window
    that catches fast/sharp moves, and a longer 15-candle (~15 min) window
    that catches slower, grinding trends which never show up as a big move
    in any single 5-minute slice (a sustained ~1-2 pt/min decline can spend
    the whole session under the short window's threshold while still adding
    up to a genuine, tradeable move over 15 minutes). Both windows can fire
    is_breakout/phase independently; either is enough.
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
                "is_exhausted": False,
                "recent_closes": [round(c, 2) for c in closes]
            }

        last = closes[-1]

        # -----------------------
        # Short window (~5 min) - fast/sharp moves
        # -----------------------

        short_move = last - closes[-6]
        short_high = max(highs[-6:-1])
        short_low = min(lows[-6:-1])

        # -----------------------
        # Long window (~15 min, or as much as is available) - slower,
        # sustained grinds that the short window alone would miss
        # -----------------------

        long_span = min(16, len(closes))
        long_move = last - closes[-long_span]
        long_high = max(highs[-long_span:-1])
        long_low = min(lows[-long_span:-1])

        # The larger-magnitude reading drives phase classification, so a
        # fast 5-min spike and a slow 15-min grind both register.
        move = short_move if abs(short_move) >= abs(long_move) else long_move

        phase = "SIDEWAYS"

        breakout = False
        breakout_direction = None
        pullback = False
        exhausted = False

        # -----------------------
        # Early Uptrend / Downtrend
        # -----------------------

        if move > 20:

            phase = "EARLY_UPTREND"

        elif move < -20:

            phase = "EARLY_DOWNTREND"

        # -----------------------
        # Breakout (either window)
        # -----------------------

        if last > short_high or last > long_high:

            breakout = True
            breakout_direction = "UP"

        if last < short_low or last < long_low:

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

            "entry_quality": quality,

            # Raw recent closes so the AI advisor can see the actual shape
            # of the last ~15 minutes, not just these derived labels.
            "recent_closes": [round(c, 2) for c in closes[-15:]]

        }
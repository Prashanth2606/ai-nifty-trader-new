
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

    `candles` is fetched with a multi-day lookback (same feed as the 5-min
    data), so it's scoped to today before use - otherwise the windows above
    would silently reach past today's first candle into the previous day's
    closing prints early in a session. Today's own opening candle is then
    dropped too: it carries the overnight gap in its open/high/low rather
    than genuine intraday movement, and including it made the first ~15
    minutes of every session read as an "exhausted" parabolic move.
    """

    # How many of the most recent candles still count as "just broke out".
    # A strict last-candle-only check flips back to False on any single
    # pause candle inside an otherwise live stair-step rally, which starved
    # the AI-confirmation gate in pipeline.py of real setups for several
    # minutes at a time. Checking the last few candles keeps a genuine
    # breakout "live" for a short window instead of flickering every tick.
    BREAKOUT_PERSIST_CANDLES = 3

    @staticmethod
    def _trading_day(time_series):
        """Buckets each candle's raw timestamp into a calendar trading day
        (see MarketAnalyzer._trading_day for the same logic/rationale)."""
        try:
            ts = pd.to_datetime(time_series, unit="s")
        except (ValueError, TypeError):
            ts = pd.to_datetime(time_series)
        return ts.dt.date

    def analyze(self, candles):

        df = pd.DataFrame(candles)

        if "time" in df.columns and not df.empty:
            df["trading_day"] = self._trading_day(df["time"])
            today = df["trading_day"].iloc[-1]
            df = df[df["trading_day"] == today].reset_index(drop=True)
            if len(df) > 1:
                df = df.iloc[1:].reset_index(drop=True)

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
        # Breakout (either window, persisted over the last few candles -
        # see BREAKOUT_PERSIST_CANDLES)
        # -----------------------

        persist_span = min(self.BREAKOUT_PERSIST_CANDLES, len(closes) - 5)

        for i in range(persist_span):

            idx = len(closes) - 1 - i

            c = closes[idx]
            s_hi = max(highs[idx - 5:idx])
            s_lo = min(lows[idx - 5:idx])

            l_span = min(15, idx)
            l_hi = max(highs[idx - l_span:idx])
            l_lo = min(lows[idx - l_span:idx])

            if c > s_hi or c > l_hi:
                breakout = True
                breakout_direction = "UP"
                break

            if c < s_lo or c < l_lo:
                breakout = True
                breakout_direction = "DOWN"
                break

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
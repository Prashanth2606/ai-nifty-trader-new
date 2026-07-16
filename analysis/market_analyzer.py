
import pandas as pd

class MarketAnalyzer:

    @staticmethod
    def _trading_day(time_series):
        """
        Buckets each candle's raw timestamp into a calendar trading day.
        Tries epoch-seconds first (Dhan's usual format), falls back to
        generic parsing for ISO strings. The ~17-18hr overnight gap between
        one day's last candle and the next day's first means a coarse day
        boundary is safe even if the exact timezone offset is off by a
        few hours - it won't split a session or merge two different ones.
        """
        try:
            ts = pd.to_datetime(time_series, unit="s")
        except (ValueError, TypeError):
            ts = pd.to_datetime(time_series)
        return ts.dt.date

    def analyze(self,candles):
        df=pd.DataFrame(candles)
        df=df[df["volume"]>0].copy().reset_index(drop=True)

        # Candles span several calendar days (fetched as one flat history
        # window) - VWAP/previous-day/opening-range all need to be scoped
        # per trading day, not accumulated/sliced across the whole window.
        df["trading_day"] = self._trading_day(df["time"])

        df["ema20"]=df["close"].ewm(span=20,adjust=False).mean()
        df["ema50"]=df["close"].ewm(span=50,adjust=False).mean()

        tp=(df["high"]+df["low"]+df["close"])/3
        tpv = tp * df["volume"]
        df["vwap"] = (
            tpv.groupby(df["trading_day"]).cumsum()
            / df["volume"].groupby(df["trading_day"]).cumsum()
        )

        latest=df.iloc[-1]
        price=float(latest["close"])
        trend="SIDEWAYS"
        if price>latest["ema20"]>latest["ema50"]:
            trend="BULLISH"
        elif price<latest["ema20"]<latest["ema50"]:
            trend="BEARISH"

        today = latest["trading_day"]
        today_rows = df[df["trading_day"] == today]
        prior_rows = df[df["trading_day"] != today]

        if not prior_rows.empty:
            last_prior_day = prior_rows["trading_day"].max()
            prior_day_rows = prior_rows[prior_rows["trading_day"] == last_prior_day]
            pdh = float(prior_day_rows["high"].max())
            pdl = float(prior_day_rows["low"].min())
        else:
            # No earlier session in the fetched window (e.g. first trading
            # day available) - fall back to today's own range so far.
            pdh = float(today_rows["high"].max())
            pdl = float(today_rows["low"].min())

        orb = today_rows.head(3)
        orb_high=float(orb["high"].max())
        orb_low=float(orb["low"].min())

        # Recent 3-candle average vs. the 3 candles right before it (last
        # ~30 min, today only) instead of a single now-vs-10-candles-ago
        # point delta. A single distant anchor point can sit right at a
        # swing low/high from earlier in the session, making "momentum"
        # read as a recovery off that stale extreme rather than what price
        # is actually doing right now - averaging both sides smooths that
        # out. Also scopes to today's candles only, matching VWAP/PDH/ORB
        # below (the old version could reach into a prior day's candle
        # early in the session).
        today_closes = today_rows["close"].tolist()

        if len(today_closes) >= 6:
            recent_avg = sum(today_closes[-3:]) / 3
            prior_avg = sum(today_closes[-6:-3]) / 3
            move = recent_avg - prior_avg
        else:
            move = 0.0

        momentum="SIDEWAYS"
        if move>40: momentum="STRONG_BULLISH"
        elif move>15: momentum="BULLISH"
        elif move<-40: momentum="STRONG_BEARISH"
        elif move<-15: momentum="BEARISH"

        return {
            "price":round(price,2),
            "ema20":round(float(latest["ema20"]),2),
            "ema50":round(float(latest["ema50"]),2),
            "vwap":round(float(latest["vwap"]),2),
            "trend":trend,
            "momentum":momentum,
            "previous_day_high":round(pdh,2),
            "previous_day_low":round(pdl,2),
            "opening_range_high":round(orb_high,2),
            "opening_range_low":round(orb_low,2),
        }

    def analyze_1min_momentum(self,candles):
        """Short-term momentum from the last 10 1-min candles (~10 minutes),
        used as a confirmation signal alongside the 5-min trend."""
        df=pd.DataFrame(candles)
        if "volume" not in df.columns or len(df)<10:
            return {"price":None,"move":0.0,"momentum":"SIDEWAYS"}
        df=df[df["volume"]>0].copy().reset_index(drop=True)
        if len(df)<10:
            return {"price":None,"move":0.0,"momentum":"SIDEWAYS"}
        price=float(df["close"].iloc[-1])
        move=df["close"].iloc[-1]-df["close"].iloc[-10]
        momentum="SIDEWAYS"
        if move>20: momentum="STRONG_BULLISH"
        elif move>8: momentum="BULLISH"
        elif move<-20: momentum="STRONG_BEARISH"
        elif move<-8: momentum="BEARISH"
        return {
            "price":round(price,2),
            "move":round(float(move),2),
            "momentum":momentum
        }

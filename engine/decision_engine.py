class DecisionEngine:
    """
    Decision Engine V3
    Conservative Option Buying Engine
    """

    def decide(self, market, option_chain, short_term=None):

        reasons = []

        recommendation = "WAIT"
        selected_trade = None

        # ------------------------
        # Extract Values
        # ------------------------

        trend = market["trend"]
        momentum = market["momentum"]

        price = market["price"]
        ema20 = market["ema20"]
        ema50 = market["ema50"]
        vwap = market["vwap"]

        short_term_momentum = short_term["momentum"] if short_term else "SIDEWAYS"

        
        # ------------------------
# Price Action
# ------------------------

        price_action = market["price_action"]

        phase = price_action["phase"]
        entry_quality = price_action["entry_quality"]

        is_breakout = price_action["is_breakout"]
        breakout_direction = price_action.get("breakout_direction")
        is_pullback = price_action["is_pullback"]
        is_exhausted = price_action["is_exhausted"]

        move = price_action["move"]

        pcr = option_chain["pcr"]
        signal = option_chain["signal"]

        support = option_chain["support"]
        resistance = option_chain["resistance"]

        bullish = 0
        bearish = 0

        # ------------------------
        # Trend
        # ------------------------

        if trend == "BULLISH":
            bullish += 1
            reasons.append("Bullish trend")

        elif trend == "BEARISH":
            bearish += 1
            reasons.append("Bearish trend")

        # ------------------------
        # EMA
        # ------------------------

        if price > ema20:
            bullish += 1
            reasons.append("Above EMA20")

        else:
            bearish += 1

        if price > ema50:
            bullish += 1
            reasons.append("Above EMA50")

        else:
            bearish += 1

        # ------------------------
        # VWAP (MANDATORY)
        # ------------------------

        if price > vwap:

            bullish += 2
            reasons.append("Above VWAP")

        else:

            bearish += 2
            reasons.append("Below VWAP")

        # ------------------------
        # PCR
        # ------------------------

        if pcr >= 1.20:
            bullish += 2
            reasons.append("Strong Bullish PCR")

        elif pcr >= 1.05:
            bullish += 1
            reasons.append("Mild Bullish PCR")

        elif pcr <= 0.80:
            bearish += 2
            reasons.append("Strong Bearish PCR")

        elif pcr <= 0.95:
            bearish += 1
            reasons.append("Mild Bearish PCR")

        else:
            reasons.append("Neutral PCR")

        # ------------------------
        # Institutional Bias
        # ------------------------

        if signal in ["PUT_WRITING", "STRONG_PUT_WRITING"]:

            bullish += 2
            reasons.append(signal)

        elif signal in ["CALL_WRITING", "STRONG_CALL_WRITING"]:

            bearish += 2
            reasons.append(signal)

        # ------------------------
        # Momentum
        # ------------------------

        if momentum == "BULLISH":

            bullish += 1
            reasons.append("Bullish Momentum")

        elif momentum == "BEARISH":

            bearish += 1
            reasons.append("Bearish Momentum")

        else:

            reasons.append("Sideways Momentum")

        # ------------------------
        # 1-Min Momentum (confirmation)
        # ------------------------

        if short_term_momentum in ["BULLISH", "STRONG_BULLISH"]:

            bullish += 1
            reasons.append(f"1-min momentum {short_term_momentum.lower()}")

        elif short_term_momentum in ["BEARISH", "STRONG_BEARISH"]:

            bearish += 1
            reasons.append(f"1-min momentum {short_term_momentum.lower()}")

        else:

            reasons.append("1-min momentum sideways")

        # ------------------------
        # PRICE ACTION
        # ------------------------

        if phase == "EARLY_UPTREND":

            bullish += 2
            reasons.append("Early Uptrend")

        elif phase == "EARLY_DOWNTREND":

            bearish += 2
            reasons.append("Early Downtrend")

        if is_breakout:

            if breakout_direction == "UP":
                bullish += 1
            elif breakout_direction == "DOWN":
                bearish += 1

            reasons.append("Breakout")

        if is_pullback:

            reasons.append("Healthy Pullback")

        if is_exhausted:

            reasons.append("Trend Exhausted")
            reasons.append("Avoid chasing move")

        # ------------------------
        # FINAL RULES
        # ------------------------

               # ------------------------
        # DECISION SCORE
        # ------------------------

        score = bullish - bearish
        
        # ------------------------
        # Entry Quality Filter
        # ------------------------

        if is_exhausted:

            if score >= 8:
                score = 5

            elif score <= -8:
                score = -5


        # Strong short-term momentum deserves extra weight
        if short_term_momentum == "STRONG_BULLISH":
            score += 2

        elif short_term_momentum == "STRONG_BEARISH":
            score -= 2

        # Near resistance/support adjustments
        if resistance and (resistance - price) <= 10:
            score -= 1
            reasons.append("Near resistance")

        if support and (price - support) <= 10:
            score += 1
            reasons.append("Near support")

        recommendation = "WAIT"
        confidence = "LOW"

        atm = option_chain.get("atm")

        # ------------------------
        # BUY CALL
        # ------------------------

        if score >= 8:

            recommendation = "BUY CALL"
            confidence = "HIGH"

            calls = option_chain["best_calls"]

            # Directional buying wants ATM/OTM leverage, not deep-ITM
            # strikes that are mostly intrinsic value.
            eligible = [c for c in calls if atm is None or c["strike"] >= atm]

            if not eligible and calls:
                eligible = calls
                reasons.append("No ATM/OTM call in range - using nearest available strike")

            if eligible:
                selected_trade = eligible[0]

        elif score >= 5:

            recommendation = "WATCH CALL"
            confidence = "MEDIUM"

        # ------------------------
        # BUY PUT
        # ------------------------

        elif score <= -8:

            recommendation = "BUY PUT"
            confidence = "HIGH"

            puts = option_chain["best_puts"]

            eligible = [p for p in puts if atm is None or p["strike"] <= atm]

            if not eligible and puts:
                eligible = puts
                reasons.append("No ATM/OTM put in range - using nearest available strike")

            if eligible:
                selected_trade = eligible[0]

        elif score <= -5:

            recommendation = "WATCH PUT"
            confidence = "MEDIUM"

        else:

            recommendation = "WAIT"

            if abs(score) >= 3:
                confidence = "MEDIUM"

        # ------------------------
        # Stop Loss / Targets (underlying Nifty levels)
        # ------------------------
        # Computed deterministically here so there's one authoritative
        # source of these levels - the AI advisor is told to narrate these
        # exact numbers rather than deriving its own.

        stop_loss = None
        target_1 = None
        target_2 = None

        if recommendation == "BUY CALL":

            stop_loss = support if support is not None else round(price - 30, 2)
            target_1 = resistance if resistance is not None else round(price + 30, 2)
            target_2 = round(price + 2 * (target_1 - price), 2)

        elif recommendation == "BUY PUT":

            stop_loss = resistance if resistance is not None else round(price + 30, 2)
            target_1 = support if support is not None else round(price - 30, 2)
            target_2 = round(price - 2 * (price - target_1), 2)

        # ------------------------
        # Confidence Consistency Cap
        # ------------------------
        # Confidence is not allowed to outrank what the tool's own
        # price-action read (entry_quality/phase/breakout) and its
        # own support/resistance levels actually support.

        rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
        label = {0: "LOW", 1: "MEDIUM", 2: "HIGH"}

        def cap_confidence(current, ceiling, note):

            nonlocal confidence

            new_rank = min(rank[current], rank[ceiling])

            if new_rank < rank[current]:
                reasons.append(note)

            confidence = label[new_rank]

            return confidence

        if recommendation in ("BUY CALL", "BUY PUT"):

            confidence = cap_confidence(
                confidence, entry_quality,
                f"Confidence capped by entry quality ({entry_quality})"
            )

            if phase == "SIDEWAYS" and not is_breakout:
                confidence = cap_confidence(
                    confidence, "MEDIUM",
                    "Sideways phase without breakout - confidence downgraded"
                )

            if recommendation == "BUY PUT" and support and (price - support) <= 25:
                confidence = cap_confidence(
                    confidence, "MEDIUM",
                    "Thin room to support - confidence downgraded"
                )

            if recommendation == "BUY CALL" and resistance and (resistance - price) <= 25:
                confidence = cap_confidence(
                    confidence, "MEDIUM",
                    "Thin room to resistance - confidence downgraded"
                )

        return {

            "recommendation": recommendation,

            "trade_quality": entry_quality,

            "confidence": confidence,

            "score": score,

            "selected_trade": selected_trade,

            "stop_loss": stop_loss,

            "target_1": target_1,

            "target_2": target_2,

            "support": support,

            "resistance": resistance,

            "pcr": pcr,

            "oi_signal": signal,

            "short_term_momentum": short_term_momentum,

            "reasons": reasons

        }
        
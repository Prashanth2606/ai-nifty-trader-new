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

        # Note: is_exhausted no longer compresses score here (that fully
        # blocked BUY CALL/PUT from ever firing, including on a move that's
        # exhausted-looking by raw magnitude but genuinely continuing, not
        # about to snap back - see the 2026-07-22 09:29 PUT that kept
        # falling another ~35pts past both targets while suppressed this
        # way). It's applied as a confidence cap below instead, so Claude
        # still gets consulted rather than the engine silently sitting out.

        # Strong short-term momentum deserves extra weight
        if short_term_momentum == "STRONG_BULLISH":
            score += 2

        elif short_term_momentum == "STRONG_BEARISH":
            score -= 2

        # entry_quality HIGH (a confirmed breakout that isn't exhausted) is a
        # faster, more reliable read than the 5-min EMA-based trend/EMA20/
        # EMA50 checks above, which lag behind a sharp reversal - seen live
        # 2026-07-23 09:52: trend read BEARISH and both EMA flags were
        # bearish (3 points of drag) purely because EMA20/50 were still
        # elevated from the pre-reversal highs, even though entry_quality
        # was already HIGH - the move then ran another ~45 points before the
        # aggregate score caught up enough to fire. Gives HIGH entry_quality
        # a comparable bonus to STRONG short-term momentum instead of
        # letting a lagging trend signal fully offset it.
        if entry_quality == "HIGH":

            if breakout_direction == "UP":
                score += 2

            elif breakout_direction == "DOWN":
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
        # 1-Min Momentum Agreement Gate
        # ------------------------
        # Trend/EMA/VWAP/OI structure alone can carry the score past the
        # BUY threshold even while the live 1-min tape is flat or moving
        # the other way (seen live on 2026-07-17 11:12: PCR/STRONG_PUT_WRITING
        # pushed score to 8 for a BUY CALL while short_term_momentum was
        # BEARISH). Require the 1-min momentum to actually agree with the
        # proposed direction, otherwise downgrade to WAIT - this is a hard
        # requirement, not just a score nudge, so it doesn't depend on some
        # unrelated gate (like the breakout flag) coincidentally catching it.

        if recommendation == "BUY CALL" and short_term_momentum not in ("BULLISH", "STRONG_BULLISH"):

            reasons.append(
                f"1-min momentum ({short_term_momentum}) does not confirm BUY CALL - downgraded to WAIT"
            )
            recommendation = "WAIT"
            confidence = "MEDIUM"
            selected_trade = None

        elif recommendation == "BUY PUT" and short_term_momentum not in ("BEARISH", "STRONG_BEARISH"):

            reasons.append(
                f"1-min momentum ({short_term_momentum}) does not confirm BUY PUT - downgraded to WAIT"
            )
            recommendation = "WAIT"
            confidence = "MEDIUM"
            selected_trade = None

        # A plain (non-STRONG) momentum reading is a single, sometimes noisy
        # signal on its own - require phase to independently confirm too
        # before trusting it alone. STRONG momentum skips this (already a
        # stronger signal by itself). Seen live 2026-07-23: a BUY PUT fired
        # at 11:53 on a single plain-BEARISH reading with phase still stuck
        # at SIDEWAYS (move only -12.2, not enough to flip phase) - it
        # reversed within minutes. The same day's 12:15 BUY PUT fired on
        # plain-BEARISH momentum too, but phase had independently confirmed
        # EARLY_DOWNTREND (move -28.35) - that one ran another ~76 points in
        # the right direction. Two independent fast signals agreeing is a
        # meaningfully different bar than one signal alone.

        elif recommendation == "BUY CALL" and short_term_momentum == "BULLISH" and phase != "EARLY_UPTREND":

            reasons.append(
                f"1-min momentum only BULLISH (not STRONG) and phase ({phase}) hasn't "
                f"independently confirmed EARLY_UPTREND - downgraded to WAIT"
            )
            recommendation = "WAIT"
            confidence = "MEDIUM"
            selected_trade = None

        elif recommendation == "BUY PUT" and short_term_momentum == "BEARISH" and phase != "EARLY_DOWNTREND":

            reasons.append(
                f"1-min momentum only BEARISH (not STRONG) and phase ({phase}) hasn't "
                f"independently confirmed EARLY_DOWNTREND - downgraded to WAIT"
            )
            recommendation = "WAIT"
            confidence = "MEDIUM"
            selected_trade = None

        # ------------------------
        # Room-to-Target Gate
        # ------------------------
        # target_1 below is set to the resistance/support level itself. If
        # price has already run up (or down) to within a few points of that
        # level, target_1 ends up almost equal to entry - and target_2,
        # derived from the entry-to-target_1 distance, collapses just as
        # badly (seen live on 2026-07-17 11:22: price 24249.1 vs resistance
        # 24250 gave a "target" 0.9 points away against a 49-point stop).
        # Reuse the same 10-point near-resistance/near-support threshold
        # already used for scoring above as a hard block - a target that
        # close isn't a real profit objective.

        if recommendation == "BUY CALL" and resistance is not None and (resistance - price) <= 10:

            reasons.append(
                f"Only {round(resistance - price, 2)} pts of room to resistance ({resistance}) "
                f"- target too close to be a real objective, downgraded to WAIT"
            )
            recommendation = "WAIT"
            confidence = "MEDIUM"
            selected_trade = None

        elif recommendation == "BUY PUT" and support is not None and (price - support) <= 10:

            reasons.append(
                f"Only {round(price - support, 2)} pts of room to support ({support}) "
                f"- target too close to be a real objective, downgraded to WAIT"
            )
            recommendation = "WAIT"
            confidence = "MEDIUM"
            selected_trade = None

        # ------------------------
        # Stop-Loss Buffer Gate
        # ------------------------
        # stop_loss for BUY CALL is set to support, for BUY PUT to resistance
        # (see below) - if price is already sitting almost on top of that
        # level, the SL ends up with near-zero buffer and the trade gets
        # stopped out by ordinary noise almost immediately, regardless of how
        # good the directional score looks (seen live on 2026-07-20 11:37:
        # BUY PUT with resistance 24200 vs price 24199.75, a 0.25-point stop -
        # AI advisor rejected it for exactly this). Threshold is wider than
        # the 10-point target-room gate above since the 1-min tape routinely
        # shows 5-8 point bounces, per that same rejection's reasoning.
        #
        # Skipped when short-term momentum is STRONG in the trade's own
        # direction - a tight buffer against a static option-chain support/
        # resistance strike is a real whipsaw risk in a range-bound market,
        # but far less so when price is actively climbing away from that
        # level under strong momentum (seen live 2026-07-23 10:04-10:10: this
        # gate held a BUY CALL back for ~5-6 minutes of a genuine, already-
        # confirmed uptrend purely because price hadn't yet drifted far
        # enough from a support strike it was already moving away from, not
        # toward).

        if (
            recommendation == "BUY CALL" and support is not None
            and (price - support) <= 15 and short_term_momentum != "STRONG_BULLISH"
        ):

            reasons.append(
                f"Only {round(price - support, 2)} pts of stop-loss buffer to support ({support}) "
                f"- stop too tight, downgraded to WAIT"
            )
            recommendation = "WAIT"
            confidence = "MEDIUM"
            selected_trade = None

        elif (
            recommendation == "BUY PUT" and resistance is not None
            and (resistance - price) <= 15 and short_term_momentum != "STRONG_BEARISH"
        ):

            reasons.append(
                f"Only {round(resistance - price, 2)} pts of stop-loss buffer to resistance ({resistance}) "
                f"- stop too tight, downgraded to WAIT"
            )
            recommendation = "WAIT"
            confidence = "MEDIUM"
            selected_trade = None

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

            if is_exhausted:
                confidence = cap_confidence(
                    confidence, "MEDIUM",
                    "Trend Exhausted (large recent move) - confidence downgraded, "
                    "not blocked, since a large move can still be a genuine "
                    "continuation rather than about to snap back"
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

            # PCR/OI can point the opposite way of the trade direction - e.g.
            # Strong Bullish PCR + PUT_WRITING at the exact strike being
            # traded typically means option writers are defending that level
            # as support, which contradicts a BUY PUT breakdown thesis right
            # at that level (seen live on 2026-07-20 11:36-11:37: PCR
            # 1.20-1.21 + PUT_WRITING on both rejected BUY PUT proposals).
            # The aggregate score already nets these against the opposing
            # direction, but nothing previously capped confidence when they
            # specifically contradict the strike actually being traded.
            pcr_bullish = pcr >= 1.05 or signal in ("PUT_WRITING", "STRONG_PUT_WRITING")
            pcr_bearish = pcr <= 0.95 or signal in ("CALL_WRITING", "STRONG_CALL_WRITING")

            if recommendation == "BUY PUT" and pcr_bullish:
                confidence = cap_confidence(
                    confidence, "MEDIUM",
                    "PCR/OI signal is bullish - contradicts BUY PUT, confidence downgraded"
                )

            elif recommendation == "BUY CALL" and pcr_bearish:
                confidence = cap_confidence(
                    confidence, "MEDIUM",
                    "PCR/OI signal is bearish - contradicts BUY CALL, confidence downgraded"
                )

            # is_breakout is direction-agnostic (true for either an up or a
            # down break), so entry_quality can read HIGH off a breakout
            # that actually points the opposite way from this trade - e.g.
            # a BUY CALL proposed while price just broke DOWN out of its
            # range. That contradiction doesn't affect score (the breakout
            # scoring above already only credits the matching direction)
            # but it did let confidence stay HIGH with nothing to catch it.
            if is_breakout and breakout_direction is not None:

                if recommendation == "BUY CALL" and breakout_direction == "DOWN":
                    confidence = cap_confidence(
                        confidence, "MEDIUM",
                        "Breakout direction (DOWN) contradicts BUY CALL - confidence downgraded"
                    )

                elif recommendation == "BUY PUT" and breakout_direction == "UP":
                    confidence = cap_confidence(
                        confidence, "MEDIUM",
                        "Breakout direction (UP) contradicts BUY PUT - confidence downgraded"
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
        
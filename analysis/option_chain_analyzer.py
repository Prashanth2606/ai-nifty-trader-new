class OptionChainAnalyzer:
    """
    Intraday Option Chain Analyzer
    """

    def analyze(self, nearby_strikes):

        if not nearby_strikes:
            return {}

        total_ce = 0
        total_pe = 0

        total_ce_change = 0
        total_pe_change = 0

        best_calls = []
        best_puts = []

        support = None
        resistance = None

        nearest_support_distance = float("inf")
        nearest_resistance_distance = float("inf")

        # Current Spot Price
        spot = nearby_strikes[0]["spot"]

        # ATM (used only for strike ranking)
        atm = min(
            nearby_strikes,
            key=lambda x: abs(x["strike"] - spot)
        )["strike"]

        # Directional option buying wants ATM/OTM leverage within realistic
        # reach of the move, not whatever strike happens to have the most
        # OI/volume - ce_score/pe_score below only discount distance by 5
        # points per index-point, which a popular round-number strike's raw
        # OI-change/volume (routinely in the tens of thousands) swamps
        # easily. A strike 150+ points past both resistance and target_2 got
        # picked as "best" this way on 2026-07-17 15:01. Excluding anything
        # beyond two strikes (100 points) from the ranking pool entirely
        # keeps the OI/volume score as a tiebreaker among realistic
        # candidates instead of letting it override proximity outright.
        MAX_STRIKE_DISTANCE = 100

        for row in nearby_strikes:

            strike = row["strike"]

            total_ce += row["ce_oi"]
            total_pe += row["pe_oi"]

            total_ce_change += row["ce_change_oi"]
            total_pe_change += row["pe_change_oi"]

            # ---------------------------------
            # Strike Ranking
            # ---------------------------------

            distance = abs(strike - atm)

            if distance <= MAX_STRIKE_DISTANCE:

                ce_score = (
                    row["ce_change_oi"] * 0.45
                    + row["ce_volume"] * 0.30
                    - row["ce_ltp"] * 0.10
                    - distance * 5
                )

                pe_score = (
                    row["pe_change_oi"] * 0.45
                    + row["pe_volume"] * 0.30
                    - row["pe_ltp"] * 0.10
                    - distance * 5
                )

                best_calls.append({

                    "strike": strike,

                    "instrument": f"{int(strike)} CE",

                    "premium": row["ce_ltp"],

                    "score": round(ce_score, 2),

                    "oi": row["ce_oi"],

                    "oi_change": row["ce_change_oi"],

                    "volume": row["ce_volume"]

                })

                best_puts.append({

                    "strike": strike,

                    "instrument": f"{int(strike)} PE",

                    "premium": row["pe_ltp"],

                    "score": round(pe_score, 2),

                    "oi": row["pe_oi"],

                    "oi_change": row["pe_change_oi"],

                    "volume": row["pe_volume"]

                })

            # ---------------------------------
            # Support
            # ---------------------------------

            if strike < spot:

                distance = spot - strike

                if distance < nearest_support_distance:

                    nearest_support_distance = distance
                    support = strike

            # ---------------------------------
            # Resistance
            # ---------------------------------

            if strike > spot:

                distance = strike - spot

                if distance < nearest_resistance_distance:

                    nearest_resistance_distance = distance
                    resistance = strike

        # ---------------------------------
        # PCR
        # ---------------------------------

        pcr = round(total_pe / total_ce, 2) if total_ce else 0

        # ---------------------------------
        # Institutional Bias
        # ---------------------------------

        signal = "NEUTRAL"

        if pcr >= 1.20 and total_pe_change > total_ce_change:
            signal = "STRONG_PUT_WRITING"

        elif pcr >= 1.05:
            signal = "PUT_WRITING"

        elif pcr <= 0.80 and total_ce_change > total_pe_change:
            signal = "STRONG_CALL_WRITING"

        elif pcr <= 0.95:
            signal = "CALL_WRITING"

        # ---------------------------------
        # Best Contracts
        # ---------------------------------

        best_calls = sorted(
            best_calls,
            key=lambda x: x["score"],
            reverse=True
        )[:5]

        best_puts = sorted(
            best_puts,
            key=lambda x: x["score"],
            reverse=True
        )[:5]

        return {

            "pcr": pcr,

            "signal": signal,

            "support": support,

            "resistance": resistance,

            "best_calls": best_calls,

            "best_puts": best_puts,

            "atm": atm,

            "spot": spot,

            "total_ce_change": total_ce_change,

            "total_pe_change": total_pe_change

        }
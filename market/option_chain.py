from broker.dhan_client import get_dhan_client, call_with_retry
import config


class OptionChain:

    def __init__(self):
        self.dhan = get_dhan_client()

    def get_raw_chain(self):

        return call_with_retry(
            self.dhan.option_chain,
            under_security_id=13,
            under_exchange_segment="IDX_I",
            expiry=config.EXPIRY
        )

    def get_atm_strike(self, chain, spot_price):

        option_data = chain["data"]["data"]["oc"]

        strikes = [float(strike) for strike in option_data.keys()]

        atm = min(
            strikes,
            key=lambda x: abs(x - spot_price)
        )

        return atm

    def get_support_resistance(self, chain):

        option_data = chain["data"]["data"]["oc"]

        max_call_oi = -1
        max_put_oi = -1

        resistance = None
        support = None

        for strike, values in option_data.items():

            strike_price = float(strike)

            ce_oi = values["ce"]["oi"]
            pe_oi = values["pe"]["oi"]

            if ce_oi > max_call_oi:
                max_call_oi = ce_oi
                resistance = strike_price

            if pe_oi > max_put_oi:
                max_put_oi = pe_oi
                support = strike_price

        return {
            "support": support,
            "resistance": resistance,
            "max_put_oi": max_put_oi,
            "max_call_oi": max_call_oi
        }

    def get_near_atm_support_resistance(self, chain, atm):

        option_data = chain["data"]["data"]["oc"]

        strikes = sorted(
            [float(strike) for strike in option_data.keys()]
        )

        nearby_strikes = [
            strike
            for strike in strikes
            if abs(strike - atm) <= 500
        ]

        max_call_oi = -1
        max_put_oi = -1

        resistance = None
        support = None

        for strike in nearby_strikes:

            strike_key = f"{strike:.6f}"

            ce_oi = option_data[strike_key]["ce"]["oi"]
            pe_oi = option_data[strike_key]["pe"]["oi"]

            if ce_oi > max_call_oi:
                max_call_oi = ce_oi
                resistance = strike

            if pe_oi > max_put_oi:
                max_put_oi = pe_oi
                support = strike

        return {
            "support": support,
            "resistance": resistance,
            "max_put_oi": max_put_oi,
            "max_call_oi": max_call_oi
        }

    def get_pcr(self, chain):

        option_data = chain["data"]["data"]["oc"]

        total_call_oi = 0
        total_put_oi = 0

        for strike, values in option_data.items():

            total_call_oi += values["ce"]["oi"]
            total_put_oi += values["pe"]["oi"]

        if total_call_oi == 0:
            return 0

        pcr = total_put_oi / total_call_oi

        return round(pcr, 2)

    def get_atm_oi_analysis(self, chain, atm):

        option_data = chain["data"]["data"]["oc"]

        strike_key = f"{atm:.6f}"

        if strike_key not in option_data:
            return None

        ce = option_data[strike_key]["ce"]
        pe = option_data[strike_key]["pe"]

        ce_oi = ce["oi"]
        ce_prev_oi = ce["previous_oi"]

        pe_oi = pe["oi"]
        pe_prev_oi = pe["previous_oi"]

        ce_change = ce_oi - ce_prev_oi
        pe_change = pe_oi - pe_prev_oi

        signal = "NEUTRAL"

        if pe_change > ce_change:
            signal = "PUT WRITING"

        elif ce_change > pe_change:
            signal = "CALL WRITING"

        return {
            "ce_oi": ce_oi,
            "ce_prev_oi": ce_prev_oi,
            "ce_change": ce_change,
            "pe_oi": pe_oi,
            "pe_prev_oi": pe_prev_oi,
            "pe_change": pe_change,
            "signal": signal
        }

    def get_nearby_strikes(
        self,
        chain,
        spot,
        count=5
    ):

        option_chain = chain["data"]["data"]["oc"]

        strikes = sorted(
            [float(k) for k in option_chain.keys()]
        )

        atm = min(
            strikes,
            key=lambda x: abs(x - spot)
        )

        atm_index = strikes.index(atm)

        start = max(0, atm_index - count)

        end = min(
            len(strikes),
            atm_index + count + 1
        )

        result = []

        for strike in strikes[start:end]:

            strike_key = f"{strike:.6f}"

            data = option_chain[strike_key]

            ce = data["ce"]
            pe = data["pe"]

            result.append({

             
                "spot": spot,

                "strike": strike,

                "ce_ltp": ce["last_price"],
                "ce_oi": ce["oi"],
                "ce_prev_oi": ce["previous_oi"],
                "ce_change_oi": ce["oi"] - ce["previous_oi"],
                "ce_volume": ce["volume"],
                "ce_iv": ce["implied_volatility"],
                           
                "pe_ltp": pe["last_price"],
                "pe_oi": pe["oi"],
                "pe_prev_oi": pe["previous_oi"],
                "pe_change_oi": pe["oi"] - pe["previous_oi"],
                "pe_volume": pe["volume"],
                "pe_iv": pe["implied_volatility"]

            })

        return result
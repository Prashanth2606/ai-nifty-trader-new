import json
import re

from ai.llm_client import LLMClient


class AIAdvisor:
    """
    Asks Claude for an independent second opinion on the engine's trade
    proposal. Claude cannot invent a new direction or data point - it can
    only CONFIRM the engine's own BUY CALL / BUY PUT proposal or REJECT it,
    acting as a skeptical trader reviewing the setup before money goes in.
    """

    def __init__(self):
        self.llm = LLMClient()

    def get_advice(self, market, option_chain, decision):

        price_action = market.get("price_action", {})
        trade = decision.get("selected_trade") or {}

        payload = {
            "market": {
                "trend": market.get("trend"),
                "momentum": market.get("momentum"),
                "short_term_momentum": decision.get("short_term_momentum"),
                "price": market.get("price"),
                "ema20": market.get("ema20"),
                "ema50": market.get("ema50"),
                "vwap": market.get("vwap")
            },

            "price_action": {
                "phase": price_action.get("phase"),
                "entry_quality": price_action.get("entry_quality"),
                "is_breakout": price_action.get("is_breakout"),
                "breakout_direction": price_action.get("breakout_direction"),
                "is_pullback": price_action.get("is_pullback"),
                "is_exhausted": price_action.get("is_exhausted"),
                "move": price_action.get("move"),
                # Oldest -> newest 1-min closes, ~last 15 minutes. Derived
                # labels above (phase/is_breakout) come from short + long
                # lookback windows and can still miss a slow grind - use
                # this raw series to judge trend persistence yourself.
                "recent_1min_closes": price_action.get("recent_closes")
            },

            "option_chain": {
                "pcr": decision.get("pcr"),
                "oi_signal": decision.get("oi_signal"),
                "support": decision.get("support"),
                "resistance": decision.get("resistance"),
                "atm": option_chain.get("atm")
            },

            "decision": {
                "recommendation": decision.get("recommendation"),
                "confidence": decision.get("confidence"),
                "trade_quality": decision.get("trade_quality"),
                "score": decision.get("score"),
                "selected_trade": trade,
                "stop_loss": decision.get("stop_loss"),
                "target_1": decision.get("target_1"),
                "target_2": decision.get("target_2"),
                "reasons": decision.get("reasons")
            }
        }

        prompt = f"""
You are an experienced, skeptical Indian Nifty Options trader reviewing a
trade a rule-based engine wants to place, before any money goes in.

The Python engine has already PROPOSED one of:

BUY CALL
BUY PUT
or
WAIT

Your job has two parts:

1. Narrate the setup for a human trader (format below).
2. Independently decide whether you would actually take this trade as
   described - not just repeat the engine's own confidence label.

IMPORTANT RULES

1. Never invent market data, ORB values, support/resistance, or confidence.
2. Use ONLY the JSON provided below. If information is unavailable, write "Not Available".
3. decision.selected_trade is the ONLY instrument being traded. Suggested Strike and Entry
   must be exactly decision.selected_trade's strike/instrument and premium - never propose
   a different strike, even if it seems like it would score better.
4. decision.stop_loss/target_1/target_2 (on the underlying Nifty index, not the option premium)
   are already computed - if recommendation is BUY CALL or BUY PUT, use these exact numbers for
   Stop Loss/Target 1/Target 2 verbatim. Do not calculate or invent your own levels. If a value
   is null, write "Not Available".
5. Keep the narration concise (within 250 words).
6. If recommendation is WAIT, explain exactly what confirmation is needed before entering, and set Verdict to N/A.
7. If recommendation is BUY CALL or BUY PUT, scrutinize the setup like a trader would before risking capital, specifically:
   - Does confidence/trade_quality actually match price_action (phase/entry_quality/breakout)? A sideways, non-breakout, non-HIGH-quality setup does not deserve blind trust even if the engine says HIGH.
   - Is selected_trade a sensible instrument for this direction (ATM/OTM for leverage) rather than deep-in-the-money (mostly intrinsic value, poor leverage)?
   - Is there enough room to the opposing support/resistance level for the trade to work before price likely reacts there?
   - Do the momentum/short-term-momentum/OI signals genuinely agree with the proposed direction, or are they mixed/contradictory?
   - Look at price_action.recent_1min_closes yourself: even if phase/is_breakout read SIDEWAYS/false (a short-window artifact), a clear sustained drift across those closes in the proposed direction is real support for the trade - don't dismiss a setup as "just chop" if the raw closes actually show a persistent grind.
8. Set Verdict to CONFIRM only if the setup holds up under this scrutiny and you would genuinely take the trade as described.
9. Set Verdict to REJECT if anything above is unconvincing, inconsistent, or too risky - explain why in Risk/Reasoning.

JSON

{json.dumps(payload, indent=2)}

Return exactly in this format:

Recommendation:

Summary:

Suggested Strike:

Entry:

Stop Loss:

Target 1:

Target 2:

Confidence:

Risk:

Reasoning:

Verdict:

The Verdict line must contain exactly one word - CONFIRM, REJECT, or N/A - and nothing else on that line (no bolding, punctuation, or extra commentary).
"""

        text = self.llm.get_trade_recommendation(prompt)

        return {
            "text": text,
            "verdict": self._parse_verdict(text)
        }

    @staticmethod
    def _parse_verdict(text):
        """
        Tolerant of formatting noise around the Verdict line (markdown bold,
        "Confirmed" vs "CONFIRM", trailing commentary, etc.) since the model
        doesn't always follow the exact-single-word instruction. REJECT is
        checked before CONFIRM so a hedged/ambiguous line ("not confirmed,
        rejecting") fails safe toward WAIT rather than toward a live trade.
        """

        if not text:
            return None

        match = re.search(r"verdict\s*:\s*(.+)", text, re.IGNORECASE)

        if not match:
            return None

        line = match.group(1).strip().upper()

        if "REJECT" in line:
            return "REJECT"

        if "CONFIRM" in line:
            return "CONFIRM"

        if "N/A" in line or "NOT APPLICABLE" in line:
            return "N/A"

        return None

"""
Full-cycle logging, separate from signal_store.py (which only records
AI-confirmed BUY CALL/PUT signals). This logs every single analyze() pass -
including WAIT/WATCH cycles - to logs/<YYYY-MM-DD>.csv so the whole day's
score/momentum timeline can be reviewed at the end of a run, not just the
moments a trade was confirmed.
"""

import csv
import os
from datetime import date, datetime

LOGS_DIR = "logs"

FIELDNAMES = [
    "time", "engine_recommendation", "ai_verdict", "final_recommendation",
    "score", "confidence", "trade_quality",
    "instrument",
    "trend", "momentum", "short_term_momentum",
    "phase", "breakout", "pullback", "exhausted", "move",
    "price", "ema20", "ema50", "vwap",
    "pcr", "oi_signal", "support", "resistance",
    "reasons",
]


def _today_file():
    os.makedirs(LOGS_DIR, exist_ok=True)
    return os.path.join(LOGS_DIR, f"{date.today().isoformat()}.csv")


def log_cycle(market, option_result, decision, engine_recommendation=None):
    """
    Appends one row for this cycle. `engine_recommendation` is the engine's
    raw pre-AI proposal for THIS cycle, passed by the caller since `decision`
    may already have been mutated (downgraded to WAIT) by the AI gate by the
    time this is called. `decision["ai_verdict"]`/`["recommendation"]` reflect
    the AI's verdict and the final gated outcome - None/unchanged when the AI
    wasn't (re)consulted this cycle (signal unchanged from last cycle).
    """

    price_action = market.get("price_action", {})
    trade = decision.get("selected_trade") or {}

    row = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "engine_recommendation": engine_recommendation
            if engine_recommendation is not None else decision.get("recommendation"),
        "ai_verdict": decision.get("ai_verdict"),
        "final_recommendation": decision.get("recommendation"),
        "score": decision.get("score"),
        "confidence": decision.get("confidence"),
        "trade_quality": decision.get("trade_quality"),
        "instrument": trade.get("instrument"),
        "trend": market.get("trend"),
        "momentum": market.get("momentum"),
        "short_term_momentum": decision.get("short_term_momentum"),
        "phase": price_action.get("phase"),
        "breakout": price_action.get("is_breakout"),
        "pullback": price_action.get("is_pullback"),
        "exhausted": price_action.get("is_exhausted"),
        "move": price_action.get("move"),
        "price": market.get("price"),
        "ema20": market.get("ema20"),
        "ema50": market.get("ema50"),
        "vwap": market.get("vwap"),
        "pcr": decision.get("pcr"),
        "oi_signal": decision.get("oi_signal"),
        "support": decision.get("support"),
        "resistance": decision.get("resistance"),
        "reasons": "; ".join(decision.get("reasons", [])),
    }

    path = _today_file()
    is_new = not os.path.exists(path)

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if is_new:
            writer.writeheader()
        writer.writerow(row)

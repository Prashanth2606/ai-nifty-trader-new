from pprint import pprint

from engine.price_action_analyzer import PriceActionAnalyzer
from market.historical_data import HistoricalDataProvider
from analysis.market_analyzer import MarketAnalyzer
from analysis.option_chain_analyzer import OptionChainAnalyzer
from engine.decision_engine import DecisionEngine
from market.option_chain import OptionChain

from ai.advisor import AIAdvisor
import run_logger


def analyze():
    """
    Runs one full Dhan-data-> rule-engine pass (no Claude call) and prints
    the market/option-chain/recommendation sections, same as app.py always
    has. Returns (market, option_result, decision) so a caller can decide
    whether narration is worth paying for before calling narrate().
    """

    print("=" * 70)
    print("AI NIFTY OPTIONS BUYING ASSISTANT")
    print("=" * 70)

    # --------------------------------------------------
    # Market Analysis
    # --------------------------------------------------

    history = HistoricalDataProvider()

    candles = history.get_5min_candles()
    candles_1m = history.get_1min_candles()

    market = MarketAnalyzer().analyze(candles)

    price_action = PriceActionAnalyzer().analyze(candles_1m)
    market["price_action"] = price_action
    short_term = MarketAnalyzer().analyze_1min_momentum(candles_1m)

    # --------------------------------------------------
    # Option Chain
    # --------------------------------------------------

    oc = OptionChain()

    chain = oc.get_raw_chain()

    spot = market["price"]

    nearby = oc.get_nearby_strikes(chain, spot)

    option_result = OptionChainAnalyzer().analyze(nearby)

    # --------------------------------------------------
    # Decision
    # --------------------------------------------------

    decision = DecisionEngine().decide(
        market,
        option_result,
        short_term
    )

    print("\nMARKET")
    print("-" * 70)

    print(f"Trend           : {market['trend']}")
    print(f"Momentum        : {market['momentum']}")
    print(f"Price           : {market['price']}")
    print(f"EMA20           : {market['ema20']}")
    print(f"EMA50           : {market['ema50']}")
    print(f"VWAP            : {market['vwap']}")
    print(f"1-min Momentum  : {decision['short_term_momentum']}")

    print("\nPRICE ACTION")
    print("-" * 70)

    print(f"Phase           : {market['price_action']['phase']}")
    print(f"Move            : {market['price_action']['move']} pts")
    print(f"Entry Quality   : {market['price_action']['entry_quality']}")
    print(f"Breakout        : {market['price_action']['is_breakout']}")
    print(f"Pullback        : {market['price_action']['is_pullback']}")
    print(f"Exhausted       : {market['price_action']['is_exhausted']}")

    print("\nOPTION CHAIN")
    print("-" * 70)

    print(f"PCR             : {decision['pcr']}")
    print(f"OI Signal       : {decision['oi_signal']}")
    print(f"Support         : {decision['support']}")
    print(f"Resistance      : {decision['resistance']}")

    print("\nENGINE SIGNAL (pre-AI-confirmation)")
    print("-" * 70)

    print(f"Trade           : {decision['recommendation']}")
    print(f"Quality         : {decision['trade_quality']}")
    print(f"Confidence      : {decision['confidence']}")
    print(f"Score           : {decision['score']}")

    trade = decision["selected_trade"]

    if trade:

        print(f"Instrument      : {trade['instrument']}")
        print(f"Premium         : {trade['premium']}")
        print(f"Stop Loss       : {decision['stop_loss']} (Nifty)")
        print(f"Target 1        : {decision['target_1']} (Nifty)")
        print(f"Target 2        : {decision['target_2']} (Nifty)")

    print("\nReasons")

    for r in decision["reasons"]:
        print("-", r)

    print("\nFull Decision Dictionary")
    print("-" * 70)

    pprint(decision)

    return market, option_result, decision


def confirm_with_ai(market, option_result, decision):
    """
    Consults Claude as an independent second opinion on the engine's trade
    proposal. Claude cannot invent a new direction - it can only CONFIRM the
    engine's own BUY CALL / BUY PUT proposal or REJECT it. A BUY is only
    ever final if Claude's verdict is CONFIRM; anything else (REJECT, a
    missing/unparseable verdict, or an API error) downgrades the
    recommendation to WAIT.

    Mutates and returns `decision` in place, plus the raw narrative text
    (or None if Claude wasn't consulted / failed).
    """

    engine_recommendation = decision["recommendation"]

    decision["engine_recommendation"] = engine_recommendation
    decision.setdefault("ai_verdict", None)
    decision.setdefault("ai_narrative", None)

    if engine_recommendation not in ("BUY CALL", "BUY PUT"):
        return decision, None

    try:
        advice = AIAdvisor().get_advice(market, option_result, decision)

    except Exception as ex:

        decision["recommendation"] = "WAIT"
        decision["reasons"].append(f"AI advisor unavailable ({ex}) - downgraded to WAIT")

        return decision, None

    decision["ai_verdict"] = advice["verdict"]
    decision["ai_narrative"] = advice["text"]

    if advice["verdict"] != "CONFIRM":

        decision["recommendation"] = "WAIT"
        decision["reasons"].append(
            f"AI advisor did not confirm (verdict={advice['verdict'] or 'unparseable'}) "
            f"- downgraded to WAIT"
        )

    return decision, advice["text"]


def narrate(market, option_result, decision):
    """
    Runs the AI confirmation gate and prints the outcome: Claude's narrative
    (if any) plus whether the engine's proposal was confirmed or downgraded.
    Returns the (possibly downgraded) decision dict.
    """

    print("\n" + "=" * 70)
    print("AI TRADE ADVISOR (CLAUDE)")
    print("=" * 70)

    engine_recommendation = decision["recommendation"]

    decision, advice_text = confirm_with_ai(market, option_result, decision)

    if advice_text:
        print(advice_text)
    elif engine_recommendation in ("BUY CALL", "BUY PUT"):
        last_reason = decision["reasons"][-1] if decision["reasons"] else "unknown error"
        print(f"Claude Error - {last_reason}")

    if engine_recommendation in ("BUY CALL", "BUY PUT"):

        print("\nFINAL RECOMMENDATION (AI-gated)")
        print("-" * 70)
        print(f"Engine proposed : {engine_recommendation}")
        print(f"AI verdict      : {decision.get('ai_verdict') or 'unparseable'}")
        print(f"Final trade     : {decision['recommendation']}")

    return decision


def run_once(call_ai=True):
    """
    Runs analyze(), then the AI confirmation gate unless call_ai=False.
    A BUY CALL / BUY PUT is only ever final if Claude confirms it - if
    call_ai=False, any engine BUY proposal is downgraded to WAIT since it
    was never reviewed. Returns the (possibly downgraded) decision dict.
    """

    market, option_result, decision = analyze()
    engine_recommendation = decision["recommendation"]

    if call_ai:
        decision = narrate(market, option_result, decision)
    else:

        print("\n" + "=" * 70)
        print("AI TRADE ADVISOR (CLAUDE)")
        print("=" * 70)
        print("(skipped this cycle to save Claude API calls)")

        decision["engine_recommendation"] = engine_recommendation
        decision["ai_verdict"] = None

        if engine_recommendation in ("BUY CALL", "BUY PUT"):
            decision["recommendation"] = "WAIT"
            decision["reasons"].append("AI confirmation skipped this cycle - downgraded to WAIT")

    run_logger.log_cycle(market, option_result, decision, engine_recommendation=engine_recommendation)

    return decision


if __name__ == "__main__":
    run_once()

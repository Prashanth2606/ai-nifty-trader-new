from datetime import datetime
from pprint import pprint

from engine.price_action_analyzer import PriceActionAnalyzer
from engine.position_monitor import PositionMonitor
from market.historical_data import HistoricalDataProvider
from analysis.market_analyzer import MarketAnalyzer
from analysis.option_chain_analyzer import OptionChainAnalyzer
from engine.decision_engine import DecisionEngine
from market.option_chain import OptionChain
from broker import order_manager

from ai.advisor import AIAdvisor
import config
import position_store
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

    # A BUY proposal with no confirmed breakout (short or long window) has
    # never once been confirmed live - it's always rejected for the same
    # reason (sideways phase, no real trigger). Skip the paid API call and
    # go straight to WAIT instead of paying to hear "reject" again.
    if not market.get("price_action", {}).get("is_breakout"):

        decision["recommendation"] = "WAIT"
        decision["reasons"].append(
            "No confirmed breakout - skipped AI call (would reject), downgraded to WAIT"
        )

        return decision, None

    try:
        advice = AIAdvisor().get_advice(market, option_result, decision)

    except Exception as ex:

        run_logger.log_ai_advisor_error(decision, ex)

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


# --------------------------------------------------------------------
# Position lifecycle - entry/exit are only ever placed from these
# functions (via broker.order_manager), and only in response to an
# explicit approval call from the UI. Nothing here places an order on its
# own initiative.
# --------------------------------------------------------------------

def reconcile_external_close(position):
    """
    Checks Dhan's actual broker position for an OPEN position's security -
    catches a position that was closed outside this app, whether by a
    manually placed order or (the expected path now) Dhan's own Bracket
    Order SL/target leg firing, since nothing else here would ever notice
    that on its own. Paper mode has no real broker position to check
    against, so it's skipped entirely.

    Returns None if the position was found closed and has been reconciled
    (closed_trades.csv row written, state cleared) - caller should treat
    this the same as any other "position no longer open" case. Returns the
    position unchanged if it's still genuinely open on Dhan's side.
    """

    if position.get("mode") != "live" or not position.get("security_id"):
        return position

    product_type = position.get("product_type", config.PRODUCT_TYPE)
    broker_position = order_manager.get_broker_position(position["security_id"], product_type)

    if broker_position is None or broker_position.get("netQty") != 0:
        return position

    exit_price = broker_position.get("sellAvg") or None

    position_store.close_position(position, exit_price=exit_price, exit_reason="CLOSED_EXTERNALLY")

    return None


def monitor_position(position):
    """
    Cheap market check for an OPEN position - skips the option-chain scan
    and AI advisor entirely, since hold/exit only depends on the Nifty
    index price vs the stop_loss/target_1 frozen into the position at
    entry-approval time (see engine/position_monitor.py).
    """

    history = HistoricalDataProvider()
    candles = history.get_5min_candles()
    market = MarketAnalyzer().analyze(candles)

    evaluation = PositionMonitor().evaluate(position, market)

    return market, evaluation


def get_current_premium(position):
    """Fresh option LTP for the open position's contract, for live P&L
    display (mirrors what Dhan's own open-positions table shows) - not used
    for any order pricing decision here."""

    option_type = "CE" if position["direction"] == "CALL" else "PE"
    return order_manager.get_option_ltp(position["strike"], option_type)


def approve_entry(position):
    """
    Places the entry order for a PENDING_ENTRY_APPROVAL position. Returns
    the resulting position (re-read from disk if a concurrent click already
    moved it on - in that case no second order is placed).
    """

    locked = position_store.transition(
        position, position_store.PENDING_ENTRY_APPROVAL, position_store.ENTRY_SUBMITTING
    )

    if locked is None:
        return position_store.read_position()

    try:
        result = order_manager.place_entry_order(locked)

    except Exception as ex:
        run_logger.log_order_error("ENTRY", locked, ex)
        position_store.transition(
            locked, position_store.ENTRY_SUBMITTING, position_store.ENTRY_ORDER_FAILED,
            error=str(ex),
        )
        return position_store.read_position()

    if result["filled"]:
        return position_store.transition(
            locked, position_store.ENTRY_SUBMITTING, position_store.OPEN,
            security_id=result["security_id"],
            entry_order_id=result["order_id"],
            entry_price=result["price"],
            entry_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            exit_managed_by_broker=result.get("exit_managed_by_broker", False),
        )

    return position_store.transition(
        locked, position_store.ENTRY_SUBMITTING, position_store.ENTRY_ORDER_PLACED,
        security_id=result["security_id"],
        entry_order_id=result["order_id"],
        entry_order_placed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        exit_managed_by_broker=result.get("exit_managed_by_broker", False),
    )


def cancel_stale_entry(position):
    """
    Cancels an entry order that's been sitting unfilled too long
    (see config.ENTRY_ORDER_TIMEOUT_SECONDS - the UI decides when it's "too
    long" and only then offers this). Closes the position out entirely
    (logged to closed_trades.csv as a no-fill, same treatment as a Dismissed
    ENTRY_ORDER_FAILED) rather than re-approving the same frozen decision at
    a new price - by this point the market may have moved enough that the
    original setup (direction, strike, whole thesis) isn't the best read
    anymore. The next cycle runs analyze() from scratch and can propose a
    genuinely different trade, not just a re-priced repeat of the old one.
    """

    order_manager.cancel_order(position, position["entry_order_id"])

    position_store.close_position(position, exit_price=None, exit_reason="CANCELLED_UNFILLED_TIMEOUT")


def poll_entry_order(position):
    """Advances ENTRY_ORDER_PLACED -> OPEN/ENTRY_ORDER_FAILED. Read-only
    against Dhan, safe to call on every rerun while a live order is pending."""

    result = order_manager.poll_order(position["entry_order_id"])

    if result["status"] == "FILLED":
        return position_store.transition(
            position, position_store.ENTRY_ORDER_PLACED, position_store.OPEN,
            entry_price=result["price"],
            entry_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    if result["status"] == "FAILED":
        return position_store.transition(
            position, position_store.ENTRY_ORDER_PLACED, position_store.ENTRY_ORDER_FAILED,
            error="Entry order was not filled by Dhan",
        )

    return position


def reject_entry(position):
    """Declines a pending entry proposal - no order is ever placed for it."""

    position_store.reject_pending_entry(position)


def request_exit(position, reason):
    """Moves OPEN -> PENDING_EXIT_APPROVAL, recording why (stop-loss hit,
    target hit, or a manual 'Exit Now' click) - this alone never places an
    order, it only surfaces the Approve Exit / Hold choice in the UI."""

    return position_store.transition(
        position, position_store.OPEN, position_store.PENDING_EXIT_APPROVAL,
        exit_reason=reason,
    )


def hold_exit(position):
    """User chose Hold over an exit recommendation - back to OPEN, will be
    re-evaluated next cycle."""

    return position_store.transition(
        position, position_store.PENDING_EXIT_APPROVAL, position_store.OPEN
    )


def approve_exit(position):
    """Places the exit order for a PENDING_EXIT_APPROVAL position."""

    locked = position_store.transition(
        position, position_store.PENDING_EXIT_APPROVAL, position_store.EXIT_SUBMITTING
    )

    if locked is None:
        return position_store.read_position()

    try:
        result = order_manager.place_exit_order(locked)

    except Exception as ex:
        run_logger.log_order_error("EXIT", locked, ex)
        position_store.transition(
            locked, position_store.EXIT_SUBMITTING, position_store.EXIT_ORDER_FAILED,
            error=str(ex),
        )
        return position_store.read_position()

    if result["filled"]:
        locked["exit_order_id"] = result["order_id"]
        position_store.close_position(
            locked, exit_price=result["price"],
            exit_reason=locked.get("exit_reason") or "MANUAL_EXIT",
        )
        return position_store.read_position()

    return position_store.transition(
        locked, position_store.EXIT_SUBMITTING, position_store.EXIT_ORDER_PLACED,
        exit_order_id=result["order_id"],
    )


def poll_exit_order(position):
    """Advances EXIT_ORDER_PLACED -> closed/EXIT_ORDER_FAILED. Read-only
    against Dhan, safe to call on every rerun while a live order is pending."""

    result = order_manager.poll_order(position["exit_order_id"])

    if result["status"] == "FILLED":
        position_store.close_position(
            position, exit_price=result["price"],
            exit_reason=position.get("exit_reason") or "MANUAL_EXIT",
        )
        return position_store.read_position()

    if result["status"] == "FAILED":
        return position_store.transition(
            position, position_store.EXIT_ORDER_PLACED, position_store.EXIT_ORDER_FAILED,
            error="Exit order was not filled by Dhan",
        )

    return position


if __name__ == "__main__":
    run_once()

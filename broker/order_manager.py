"""
The only module in this codebase allowed to call Dhan's order-placement
endpoints (place_order / get_order_by_id). Every function here is gated by
config.TRADING_MODE: "paper" never constructs an authenticated order call at
all (broker.dhan_client.get_dhan_client() isn't even invoked on that path);
only "live" places a real order on the real Dhan account.

CAUTION - unverified assumption: Dhan's REST place_order/get_order_by_id
response field names (orderId / orderStatus / averageTradedPrice) are
inferred from Dhan's public API convention and this SDK's camelCase request
payload style, not confirmed against a live response - no test order was
placed to verify this while building the feature (that would itself be
placing a real trade). The first live Approve click should be watched
closely; if an expected key is missing, _extract_order_id/_extract_fill_price
raise with the full raw response attached rather than silently guessing, so
the fix is a one-line key-name change once the real shape is seen.

place_entry_order/place_exit_order return {"filled": bool, "order_id": str,
"security_id": str|None, "price": float|None} - "filled" tells the caller
whether this order is already terminal (paper mode, always instant) or
still needs poll_order() on subsequent reruns (live mode, MARKET orders
usually fill fast but aren't guaranteed synchronous).
"""

import uuid
from datetime import datetime

from dhanhq import dhanhq

import config
import run_logger
from broker.dhan_client import get_dhan_client, call_with_retry
from broker.security_master import resolve_security_id
from market.option_chain import OptionChain


class OrderPlacementError(Exception):
    pass


class OrderResponseShapeError(Exception):
    """Dhan's response didn't contain a field this code expects to find -
    surfaces the raw response rather than guessing, since this sits on a
    real-money path."""


def _extract_order_id(response):
    data = response.get("data") or {}
    for key in ("orderId", "order_id", "orderNo"):
        if key in data:
            return str(data[key])
    raise OrderResponseShapeError(f"No recognizable order id field in response: {response}")


def _extract_fill_price(data):
    for key in ("averageTradedPrice", "price", "tradedPrice"):
        if data.get(key):
            return float(data[key])
    return None


def _map_order_status(raw_status):
    """Dhan's order status string -> FILLED / FAILED / PENDING. Unknown
    strings are treated as PENDING (keep polling) rather than guessed either
    way; the raw string is available in the caller's response for display."""

    filled = {"TRADED", "EXECUTED"}
    failed = {"REJECTED", "CANCELLED", "EXPIRED"}

    status = (raw_status or "").upper()

    if status in filled:
        return "FILLED"
    if status in failed:
        return "FAILED"
    return "PENDING"


def _security_id_and_lot_size(position):
    option_type = "CE" if position["direction"] == "CALL" else "PE"
    security_id, lot_size = resolve_security_id(position["strike"], option_type)

    if lot_size != config.LOT_SIZE:
        raise OrderPlacementError(
            f"Lot size mismatch: Dhan security master says {lot_size} for "
            f"{position['instrument']}, but config.LOT_SIZE is {config.LOT_SIZE}. "
            f"Refusing to place order - update config.LOT_SIZE if NSE has "
            f"revised the Nifty lot size."
        )

    return security_id, lot_size


def get_option_ltp(strike, option_type):
    """Fresh LTP for one specific contract - used for paper-mode fills, Super
    Order entry limit pricing, and live P&L display. Live fills use the order's
    actual traded price instead, this is never used to determine a live
    entry/exit fill price after the fact."""

    chain = OptionChain().get_raw_chain()
    strike_key = f"{float(strike):.6f}"
    leg = "ce" if option_type == "CE" else "pe"
    return chain["data"]["data"]["oc"][strike_key][leg]["last_price"]


def place_entry_order(position):
    """
    Live mode tries a Super Order first - one order that gives Dhan the
    entry plus config.SUPER_ORDER_STOP_LOSS_POINTS/SUPER_ORDER_PROFIT_POINTS
    as resting ENTRY_LEG/TARGET_LEG/STOP_LOSS_LEG legs it manages itself
    from the moment entry fills, instead of relying on this app polling
    price and you clicking Approve Exit.

    NOT "Bracket Order" (BO) - Dhan confirmed directly (2026-07-23) BO isn't
    supported via their API at all (always DH-906 "Transactions Fails",
    funds/segment irrelevant - it's simply not wired up on the API side).
    Super Order (dhanhq's place_super_order, POSTs to /super/orders) is
    confirmed working via a read-only check against this same account
    (2026-07-23: another tool already has live Super Orders running here,
    e.g. correlationId "VTT_Position" - proof the endpoint is genuinely
    usable, not just per Dhan support's word, which was inconsistent across
    different answers on this same question).

    Uses product_type=MARGIN, matching what that other tool's working
    orders use - untested whether INTRA would also work for Super Order,
    MARGIN is the only combination confirmed live on this account so far.

    Falls back to a plain MARKET/INTRA order with no SL/target attached (the
    original pre-BO/Super-Order behavior) if the Super Order attempt fails
    for any reason, rather than leaving you unable to enter at all. Returns
    super_order_fallback=True in that case so the UI can warn that SL/target
    need to be added manually in Dhan.
    """

    security_id, _ = _security_id_and_lot_size(position)

    if config.TRADING_MODE == "paper":
        return {
            "filled": True,
            "order_id": f"PAPER-{uuid.uuid4()}",
            "security_id": security_id,
            "price": position["decision_snapshot"]["premium"],
            "exit_managed_by_broker": False,
            "super_order_fallback": False,
            "product_type": config.PRODUCT_TYPE,
        }

    option_type = "CE" if position["direction"] == "CALL" else "PE"
    entry_price = get_option_ltp(position["strike"], option_type)
    target_price = round(entry_price + config.SUPER_ORDER_PROFIT_POINTS, 2)
    stop_loss_price = round(entry_price - config.SUPER_ORDER_STOP_LOSS_POINTS, 2)

    try:
        if stop_loss_price <= 0:
            raise ValueError(
                f"Computed stop_loss_price {stop_loss_price} <= 0 "
                f"(entry_price={entry_price} - {config.SUPER_ORDER_STOP_LOSS_POINTS})"
            )

        so_response = call_with_retry(
            get_dhan_client().place_super_order,
            security_id=security_id,
            exchange_segment=dhanhq.FNO,
            transaction_type=dhanhq.BUY,
            quantity=config.LOT_SIZE,
            order_type=dhanhq.LIMIT,
            product_type=dhanhq.MARGIN,
            price=entry_price,
            targetPrice=target_price,
            stopLossPrice=stop_loss_price,
            # tag/correlationId deliberately omitted (it's optional per
            # Dhan's docs) - seen live 2026-07-23 11:56: a DH-905 "missing
            # required fields, bad values for parameters" rejection with our
            # full UUID correlation_id passed as tag, while the one proven-
            # working Super Order example found on this account used a
            # short plain string ("VTT_Position") for correlationId, not a
            # UUID - a real candidate for Dhan rejecting the UUID's
            # format/length. This app already tracks its own order_id for
            # traceability, so correlationId isn't needed here.
        )
    except Exception as ex:
        # place_super_order also raises ValueError client-side for invalid
        # inputs (see its own validation) - treated the same as an HTTP
        # rejection here, both fall through to the plain-order fallback.
        so_response = {"status": "failure", "remarks": {"error_message": str(ex)}, "data": ""}

    # Log the actual request parameters alongside the response - a DH-905
    # "missing required fields, bad values" rejection (seen live
    # 2026-07-23 11:56) needs the values that were actually sent to
    # diagnose, since the SDK's own client-side validation already passed
    # (this was a genuine server-side rejection) and log_order_response
    # only otherwise captures the response, not the request.
    print(
        f"Dhan place_super_order (ENTRY) request: security_id={security_id} "
        f"price={entry_price} targetPrice={target_price} stopLossPrice={stop_loss_price} "
        f"quantity={config.LOT_SIZE}"
    )
    print(f"Dhan place_super_order (ENTRY) response: {so_response}")
    run_logger.log_order_response(
        "ENTRY_SUPER_ORDER", position,
        {
            "request": {
                "security_id": security_id, "price": entry_price,
                "targetPrice": target_price, "stopLossPrice": stop_loss_price,
                "quantity": config.LOT_SIZE,
            },
            "response": so_response,
        },
    )

    if so_response.get("status") == "success":
        order_id = _extract_order_id(so_response)
        run_logger.log_order_execution("ENTRY", position, order_id, status="SUBMITTED")

        return {
            "filled": False,
            "order_id": order_id,
            "security_id": security_id,
            "price": None,
            "exit_managed_by_broker": True,
            "super_order_fallback": False,
            # Super Order was placed with product_type=MARGIN (see docstring) -
            # the resulting position is tracked under that product type in
            # Dhan's own position book, not INTRADAY, so both external-close
            # reconciliation (get_broker_position) and a manual square-off
            # sell need to match against MARGIN for this specific position.
            "product_type": dhanhq.MARGIN,
        }

    # Super Order rejected - fall back to a plain order rather than blocking
    # entry entirely. No SL/target attached here - the caller/UI must warn
    # this needs to be added manually in Dhan.
    plain_response = call_with_retry(
        get_dhan_client().place_order,
        security_id=security_id,
        exchange_segment=dhanhq.FNO,
        transaction_type=dhanhq.BUY,
        quantity=config.LOT_SIZE,
        order_type=dhanhq.MARKET,
        product_type=dhanhq.INTRA,
        price=0,
        trigger_price=0,
        validity=dhanhq.DAY,
    )

    print(f"Dhan place_order (ENTRY, plain fallback) response: {plain_response}")
    run_logger.log_order_response("ENTRY_PLAIN_FALLBACK", position, plain_response)

    if plain_response.get("status") != "success":
        raise OrderPlacementError(
            f"Entry order rejected by Dhan - both Super Order ({so_response}) and "
            f"plain-order fallback ({plain_response}) failed."
        )

    order_id = _extract_order_id(plain_response)
    run_logger.log_order_execution("ENTRY", position, order_id, status="SUBMITTED (Super Order fallback)")

    return {
        "filled": False,
        "order_id": order_id,
        "security_id": security_id,
        "price": None,
        "exit_managed_by_broker": False,
        "super_order_fallback": True,
        "product_type": dhanhq.INTRA,
    }


class SuperOrderLegCancelError(Exception):
    """Couldn't cancel a Super Order position's resting target/stop-loss
    legs before a manual exit - deliberately fatal (see
    cancel_super_order_legs) rather than proceeding to place a square-off
    sell alongside legs that might still be resting, which could
    double-sell."""


def cancel_super_order_legs(position):
    """
    Cancels the resting TARGET_LEG/STOP_LOSS_LEG of a Super Order position
    before a manual exit - without this, a manual square-off sell placed
    alongside still-resting legs could fill twice (the manual sell plus
    whichever leg fires first), leaving a naked short.

    Unlike the old BO approach (which had to search get_order_list() and
    guess at field names), Dhan's cancel_super_order(order_id, leg_name)
    takes the entry order's own order_id directly - this app already has
    that stored on the position, so no lookup/guessing is needed here.
    """

    order_id = position["entry_order_id"]

    for leg_name in ("TARGET_LEG", "STOP_LOSS_LEG"):

        response = call_with_retry(get_dhan_client().cancel_super_order, order_id, leg_name)
        print(f"Dhan cancel_super_order ({leg_name}) response: {response}")

        if response.get("status") != "success":
            raise SuperOrderLegCancelError(
                f"Failed to cancel Super Order {leg_name} for order {order_id}: {response}"
            )

        run_logger.log_order_execution(f"CANCEL_{leg_name}", position, order_id, status="CANCELLED")


def place_exit_order(position):
    """Reuses the security_id already resolved and stored on the position at
    entry time - no need to re-resolve it. For a broker-managed (Super
    Order) position, cancels the resting target/stop-loss legs first (see
    cancel_super_order_legs) so this square-off can't collide with one of
    them filling independently."""

    security_id = position["security_id"]

    if config.TRADING_MODE == "paper":
        option_type = "CE" if position["direction"] == "CALL" else "PE"
        try:
            exit_price = get_option_ltp(position["strike"], option_type)
        except Exception:
            # Best-effort for paper P&L display only - fall back to the
            # entry premium rather than blocking a simulated exit.
            exit_price = position.get("entry_price")

        return {
            "filled": True,
            "order_id": f"PAPER-{uuid.uuid4()}",
            "security_id": security_id,
            "price": exit_price,
        }

    if position.get("exit_managed_by_broker"):
        cancel_super_order_legs(position)

    response = call_with_retry(
        get_dhan_client().place_order,
        security_id=security_id,
        exchange_segment=dhanhq.FNO,
        transaction_type=dhanhq.SELL,
        quantity=position["quantity"],
        order_type=dhanhq.MARKET,
        # Must match whatever product_type entry actually used (MARGIN for a
        # successful Super Order, INTRADAY for the plain-order fallback/pre-
        # Super-Order behavior) - Dhan tracks the position under that same
        # product type, and squaring off under the wrong one may not net it
        # off correctly. See product_type handling in place_entry_order.
        product_type=position.get("product_type") or dhanhq.INTRA,
        price=0,
        trigger_price=0,
        validity=dhanhq.DAY,
    )

    print(f"Dhan place_order (EXIT) response: {response}")
    run_logger.log_order_response("EXIT", position, response)

    if response.get("status") != "success":
        raise OrderPlacementError(f"Exit order rejected by Dhan: {response}")

    order_id = _extract_order_id(response)
    run_logger.log_order_execution("EXIT", position, order_id, status="SUBMITTED")

    return {
        "filled": False,
        "order_id": order_id,
        "security_id": security_id,
        "price": None,
    }


def cancel_order(position, order_id):
    """Cancels a resting order - used to cancel a stale unfilled Super Order/
    plain entry LIMIT order so a fresh Approve click can re-price at the
    current LTP instead of leaving the old order resting all day untouched."""

    response = call_with_retry(get_dhan_client().cancel_order, order_id)

    print(f"Dhan cancel_order response: {response}")
    run_logger.log_order_response("CANCEL", position, response)

    if response.get("status") == "success":
        run_logger.log_order_execution("CANCEL_ENTRY", position, order_id, status="CANCELLED")

    return response


def get_broker_position(security_id, product_type):
    """Read-only lookup into Dhan's actual net position for this security -
    used to detect a position that was closed outside this app (e.g. a
    manually placed stop-loss order filling on Dhan's side), since nothing
    else here polls for that. Matches on both security_id and product_type,
    since Dhan can return multiple rows for the same security across
    different product types (e.g. MARGIN vs INTRADAY). Returns None if no
    matching row exists (nothing ever bought under this security/product)."""

    response = call_with_retry(get_dhan_client().get_positions)

    if response.get("status") != "success":
        return None

    for row in response.get("data") or []:
        if str(row.get("securityId")) == str(security_id) and row.get("productType") == product_type:
            return row

    return None


def poll_order(order_id):
    """Read-only - safe to call on every Streamlit rerun while an order is
    in flight. Returns {"status": FILLED|FAILED|PENDING, "price": float|None}.
    Paper orders never reach this (place_*_order returns filled=True for
    them immediately), but a "PAPER-" id is handled defensively anyway."""

    if order_id and order_id.startswith("PAPER-"):
        return {"status": "FILLED", "price": None}

    response = call_with_retry(get_dhan_client().get_order_by_id, order_id)

    if response.get("status") != "success":
        return {"status": "PENDING", "price": None}

    data = response.get("data") or {}
    if isinstance(data, list):
        data = data[0] if data else {}

    raw_status = data.get("orderStatus") or data.get("status")
    status = _map_order_status(raw_status)
    price = _extract_fill_price(data) if status == "FILLED" else None

    return {"status": status, "price": price}

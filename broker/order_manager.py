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
    """Fresh LTP for one specific contract - used for paper-mode fills, BO
    entry limit pricing, and live P&L display. Live fills use the order's
    actual traded price instead, this is never used to determine a live
    entry/exit fill price after the fact."""

    chain = OptionChain().get_raw_chain()
    strike_key = f"{float(strike):.6f}"
    leg = "ce" if option_type == "CE" else "pe"
    return chain["data"]["data"]["oc"][strike_key][leg]["last_price"]


def place_entry_order(position):

    security_id, _ = _security_id_and_lot_size(position)

    if config.TRADING_MODE == "paper":
        return {
            "filled": True,
            "order_id": f"PAPER-{uuid.uuid4()}",
            "security_id": security_id,
            "price": position["decision_snapshot"]["premium"],
        }

    response = call_with_retry(
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

    print(f"Dhan place_order (ENTRY) response: {response}")
    run_logger.log_order_response("ENTRY", position, response)

    if response.get("status") != "success":
        raise OrderPlacementError(f"Entry order rejected by Dhan: {response}")

    return {
        "filled": False,
        "order_id": _extract_order_id(response),
        "security_id": security_id,
        "price": None,
    }


def place_exit_order(position):
    """Reuses the security_id already resolved and stored on the position at
    entry time - no need to re-resolve it."""

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

    response = call_with_retry(
        get_dhan_client().place_order,
        security_id=security_id,
        exchange_segment=dhanhq.FNO,
        transaction_type=dhanhq.SELL,
        quantity=position["quantity"],
        order_type=dhanhq.MARKET,
        product_type=dhanhq.INTRA,
        price=0,
        trigger_price=0,
        validity=dhanhq.DAY,
    )

    print(f"Dhan place_order (EXIT) response: {response}")
    run_logger.log_order_response("EXIT", position, response)

    if response.get("status") != "success":
        raise OrderPlacementError(f"Exit order rejected by Dhan: {response}")

    return {
        "filled": False,
        "order_id": _extract_order_id(response),
        "security_id": security_id,
        "price": None,
    }


def cancel_order(position, order_id):
    """Cancels a resting order - used to cancel a stale unfilled BO entry
    LIMIT order so a fresh Approve click can re-price at the current LTP
    instead of leaving the old order resting all day untouched."""

    response = call_with_retry(get_dhan_client().cancel_order, order_id)

    print(f"Dhan cancel_order response: {response}")
    run_logger.log_order_response("CANCEL", position, response)

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

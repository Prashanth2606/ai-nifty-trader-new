"""
File-based persistence for the single live position lifecycle (entry
approval -> order -> open -> exit approval -> order -> closed). Modeled on
signal_store.py's file-based pattern, but deliberately NOT date-scoped or
cleaned up daily - a trade history should persist, and only one position is
ever active/pending at a time (position/state.json absent means no position).

Streamlit reruns the whole script on every interaction/auto-refresh, so this
state has to live on disk, not in st.session_state, to survive that - same
reason signal_store.py's .state.json exists.
"""

import csv
import json
import os
import uuid
from datetime import datetime

import config

POSITION_DIR = "position"
STATE_FILE = os.path.join(POSITION_DIR, "state.json")
HISTORY_FILE = os.path.join(POSITION_DIR, "closed_trades.csv")

HISTORY_FIELDNAMES = [
    "closed_at", "correlation_id", "direction", "instrument", "mode",
    "quantity", "security_id", "entry_order_id", "entry_price", "entry_time",
    "exit_order_id", "exit_price", "exit_time",
    "exit_reason", "pnl_per_unit", "pnl_total",
]

PENDING_ENTRY_APPROVAL = "PENDING_ENTRY_APPROVAL"
# ENTRY_SUBMITTING is a short-lived lock held for the duration of the actual
# place_order network call - it's what the double-click/idempotency guard
# transitions into immediately on an Approve click, before the outcome
# (filled, order-placed-but-pending, or failed) is known.
ENTRY_SUBMITTING = "ENTRY_SUBMITTING"
ENTRY_ORDER_PLACED = "ENTRY_ORDER_PLACED"
ENTRY_ORDER_FAILED = "ENTRY_ORDER_FAILED"
OPEN = "OPEN"
PENDING_EXIT_APPROVAL = "PENDING_EXIT_APPROVAL"
EXIT_SUBMITTING = "EXIT_SUBMITTING"
EXIT_ORDER_PLACED = "EXIT_ORDER_PLACED"
EXIT_ORDER_FAILED = "EXIT_ORDER_FAILED"


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _write_state(position):
    os.makedirs(POSITION_DIR, exist_ok=True)
    tmp_path = STATE_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(position, f, indent=2)
    os.replace(tmp_path, STATE_FILE)


def read_position():
    if not os.path.exists(STATE_FILE):
        return None
    with open(STATE_FILE, encoding="utf-8") as f:
        return json.load(f)


def create_pending_entry(decision, mode):
    """
    Freezes the AI-confirmed decision into a new pending position. Only
    called when read_position() is None - the caller is responsible for
    that check (this module doesn't enforce "at most one position" itself,
    since the file's mere existence is what callers already branch on).
    """

    trade = decision.get("selected_trade") or {}
    direction = "CALL" if decision["recommendation"] == "BUY CALL" else "PUT"

    position = {
        "correlation_id": str(uuid.uuid4()),
        "status": PENDING_ENTRY_APPROVAL,
        "direction": direction,
        "instrument": trade.get("instrument"),
        "strike": trade.get("strike"),
        "quantity": config.LOT_SIZE,
        "mode": mode,
        "product_type": config.PRODUCT_TYPE,
        "exit_managed_by_broker": False,
        "decision_snapshot": {
            "premium": trade.get("premium"),
            "stop_loss": decision.get("stop_loss"),
            "target_1": decision.get("target_1"),
            "target_2": decision.get("target_2"),
            "confidence": decision.get("confidence"),
            "reasons": decision.get("reasons", []),
        },
        "security_id": None,
        "entry_order_id": None,
        "entry_order_placed_at": None,
        "entry_price": None,
        "entry_time": None,
        "exit_order_id": None,
        "exit_price": None,
        "exit_time": None,
        "exit_reason": None,
        "error": None,
        "created_at": _now(),
    }

    _write_state(position)
    return position


def transition(position, expected_status, new_status, **updates):
    """
    Atomic compare-and-swap: re-reads the state file fresh and only applies
    the transition if both the correlation_id and status still match what
    the caller expects. Returns the updated position on success, or None if
    another click/rerun already moved it on - callers must treat None as
    "do nothing further" (in particular: never place an order after a None).
    """

    current = read_position()

    if current is None:
        return None

    if current.get("correlation_id") != position.get("correlation_id"):
        return None

    if current.get("status") != expected_status:
        return None

    current["status"] = new_status
    current.update(updates)
    _write_state(current)
    return current


def close_position(position, exit_price, exit_reason):
    """
    Appends one permanent history row and clears the active position file.
    P&L is always (exit_premium - entry_premium) * quantity - this tool only
    ever buys options to enter and sells to exit, for both CALL and PUT.
    """

    os.makedirs(POSITION_DIR, exist_ok=True)

    entry_price = position.get("entry_price")
    pnl_per_unit = (
        round(exit_price - entry_price, 2)
        if exit_price is not None and entry_price is not None
        else None
    )
    quantity = position.get("quantity") or 0

    row = {
        "closed_at": _now(),
        "correlation_id": position.get("correlation_id"),
        "direction": position.get("direction"),
        "instrument": position.get("instrument"),
        "mode": position.get("mode"),
        "quantity": quantity,
        # Dhan's own order/security IDs, kept on the permanent record for
        # audit-trail traceability back to the broker's own order book -
        # previously only lived in position/state.json while a position was
        # open and got dropped the moment it closed.
        "security_id": position.get("security_id"),
        "entry_order_id": position.get("entry_order_id"),
        "entry_price": entry_price,
        "entry_time": position.get("entry_time"),
        "exit_order_id": position.get("exit_order_id"),
        "exit_price": exit_price,
        "exit_time": _now(),
        "exit_reason": exit_reason,
        "pnl_per_unit": pnl_per_unit,
        "pnl_total": round(pnl_per_unit * quantity, 2) if pnl_per_unit is not None else None,
    }

    is_new = not os.path.exists(HISTORY_FILE)
    with open(HISTORY_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_FIELDNAMES)
        if is_new:
            writer.writeheader()
        writer.writerow(row)

    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)


def reject_pending_entry(position):
    """
    Atomically closes a PENDING_ENTRY_APPROVAL position as rejected (logs a
    row to closed_trades.csv for a complete audit trail, then clears the
    state file). Returns True if this call performed the rejection, False
    if the position had already moved on - the same double-click guard as
    transition(), since there's no order to submit here to naturally gate on.
    """

    current = read_position()

    if current is None:
        return False

    if current.get("correlation_id") != position.get("correlation_id"):
        return False

    if current.get("status") != PENDING_ENTRY_APPROVAL:
        return False

    close_position(current, exit_price=None, exit_reason="REJECTED_BY_USER")
    return True


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def clear_history():
    if os.path.exists(HISTORY_FILE):
        os.remove(HISTORY_FILE)

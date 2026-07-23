"""
Local web UI for the analysis pipeline (replaces watching run_loop.py in a
terminal). Each page load/auto-refresh runs one pipeline.analyze() cycle,
same as run_loop.py; Claude is only asked to narrate when the recommendation
changes, also same as run_loop.py. BUY CALL / BUY PUT signals are appended
to a today-dated CSV (via signal_store) so they stay visible in a dedicated,
highlighted table until end of day regardless of page reloads.

When an AI-confirmed BUY CALL/PUT appears and no position is already open or
pending, it becomes a position awaiting your approval (position_store.py) -
approving places a real order via broker/order_manager.py. Once open, each
cycle checks the position against its stop-loss/target and, if triggered,
asks for exit approval the same way. No order (entry or exit) is ever
placed without an explicit button click here.

Usage:
    streamlit run webapp.py
"""

from datetime import datetime

import pandas as pd
import streamlit as st

import config
import pipeline
from pipeline import analyze, confirm_with_ai
import position_store
import signal_store
import run_logger

st.set_page_config(page_title="AI Nifty Options Assistant", layout="wide")

signal_store.cleanup_old_files()

st.title("AI Nifty Options Buying Assistant")

if config.TRADING_MODE == "live":
    st.error("🔴 LIVE MODE - approving a trade below places a real order on your Dhan account.")
else:
    st.warning("🟡 PAPER MODE - approvals simulate a fill, no real order is placed.")

with st.sidebar:
    st.header("Controls")
    auto_refresh = st.checkbox("Auto-refresh", value=True)
    interval = st.number_input(
        "Interval (seconds)", min_value=5, max_value=300, value=20, step=5
    )
    call_ai = st.checkbox("Ask Claude to confirm signal before final BUY", value=True)
    run_now = st.button("Run Now")

    st.divider()

    if st.button("Clear today's signals"):
        signal_store.clear_today()
        st.rerun()

    if st.button("Clear closed trades"):
        position_store.clear_history()
        st.rerun()

if "session_has_run" not in st.session_state:
    st.session_state.session_has_run = False

should_run = run_now or auto_refresh or not st.session_state.session_has_run

position = position_store.read_position()

market = option_result = decision = None
position_market = None
position_evaluation = None

if should_run:
    st.session_state.session_has_run = True

    try:
        if position is None:

            # --------------------------------------------------
            # No open/pending position - scan for a new signal,
            # exactly as before this feature existed.
            # --------------------------------------------------

            with st.spinner("Fetching Dhan data and running decision engine..."):
                market, option_result, decision = analyze()

            engine_recommendation = decision.get("recommendation")
            engine_instrument = (decision.get("selected_trade") or {}).get("instrument")

            last_recommendation = signal_store.read_last_recommendation()
            last_instrument = signal_store.read_last_instrument()

            # Re-confirm with Claude whenever the proposal OR the underlying
            # strike changes - if only the recommendation label were compared,
            # the engine flipping strikes (e.g. 24000 PE -> 24200 PE) while
            # still saying "BUY PUT" would silently keep showing Claude's old,
            # now-mismatched narrative for the previous strike.
            changed = (
                engine_recommendation != last_recommendation
                or engine_instrument != last_instrument
            )

            if changed:

                advice = None

                # Claude is only ever consulted for an actual BUY CALL/PUT
                # proposal - WAIT/WATCH cycles never call the API, since there's
                # no trade to confirm/reject and narrating them was pure cost
                # with no decision-relevant payoff.
                if engine_recommendation in ("BUY CALL", "BUY PUT"):

                    if call_ai:
                        # A BUY only becomes final if Claude's independent review
                        # confirms it - confirm_with_ai downgrades to WAIT otherwise.
                        with st.spinner("Asking Claude to confirm the signal..."):
                            decision, advice = confirm_with_ai(market, option_result, decision)
                    else:
                        # AI confirmation disabled - an unreviewed BUY can't be final.
                        decision["engine_recommendation"] = engine_recommendation
                        decision["recommendation"] = "WAIT"
                        decision["ai_verdict"] = None
                        decision["reasons"].append("AI confirmation disabled - downgraded to WAIT")

                if advice is not None:
                    signal_store.write_last_advice(advice)

                recommendation = decision["recommendation"]

                # Append the signal row (the durable record) before marking the
                # recommendation as "seen" — if this raises, last_recommendation
                # must stay stale so the next cycle retries instead of silently
                # dropping the signal. Only a Claude-confirmed BUY is logged.
                if recommendation in ("BUY CALL", "BUY PUT"):
                    trade = decision.get("selected_trade") or {}
                    signal_store.append_signal({
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "recommendation": recommendation,
                        "instrument": trade.get("instrument"),
                        "premium": trade.get("premium"),
                        "confidence": decision.get("confidence"),
                        "trend": market.get("trend"),
                        "momentum": market.get("momentum"),
                        "short_term_momentum": decision.get("short_term_momentum"),
                        "price": market.get("price"),
                        "ema20": market.get("ema20"),
                        "ema50": market.get("ema50"),
                        "vwap": market.get("vwap"),
                        "pcr": decision.get("pcr"),
                        "oi_signal": decision.get("oi_signal"),
                        "support": decision.get("support"),
                        "resistance": decision.get("resistance"),
                        "stop_loss": decision.get("stop_loss"),
                        "target_1": decision.get("target_1"),
                        "target_2": decision.get("target_2"),
                        "reasons": "; ".join(decision.get("reasons", [])),
                    })

                    # A confirmed BUY becomes a position awaiting your
                    # approval - this alone never places an order.
                    position = position_store.create_pending_entry(decision, config.TRADING_MODE)

                final_instrument = (
                    (decision.get("selected_trade") or {}).get("instrument")
                    if recommendation in ("BUY CALL", "BUY PUT") else None
                )

                signal_store.write_last_recommendation(recommendation)
                signal_store.write_last_instrument(final_instrument)

            run_logger.log_cycle(market, option_result, decision, engine_recommendation=engine_recommendation)

        elif position["status"] == position_store.ENTRY_ORDER_PLACED:
            position = pipeline.poll_entry_order(position) or position

        elif position["status"] == position_store.EXIT_ORDER_PLACED:
            position = pipeline.poll_exit_order(position)

        elif position["status"] == position_store.PENDING_EXIT_APPROVAL:
            # A position can reach here from our own internal Nifty-level
            # SL/target check, but the underlying instrument may already be
            # flat on Dhan's side by the time you see this prompt - e.g. a
            # manually placed trailing SL firing first (seen live on
            # 2026-07-20 12:48). Re-checking here means "Approve Exit" never
            # gets clicked against an already-closed position, which would
            # otherwise place an unwanted fresh sell order.
            position = pipeline.reconcile_external_close(position)

        elif position["status"] == position_store.OPEN:
            position = pipeline.reconcile_external_close(position)
            if position is not None:
                with st.spinner("Checking position against stop-loss/target..."):
                    position_market, position_evaluation = pipeline.monitor_position(position)
                # Broker-managed (Bracket Order) positions exit via Dhan's own
                # resting SL/target legs, caught next cycle by
                # reconcile_external_close above - triggering our own
                # approval-gated exit here too would place a second, unrelated
                # sell order against those still-resting legs.
                if position_evaluation["action"] == "EXIT" and not position.get("exit_managed_by_broker"):
                    position = pipeline.request_exit(position, position_evaluation["reason"]) or position

        # PENDING_ENTRY_APPROVAL / *_FAILED: nothing to scan or poll - just
        # waiting on a button click below. (PENDING_EXIT_APPROVAL is handled
        # above - it still needs reconcile_external_close, see that branch.)

    except Exception as ex:
        st.error(f"Cycle failed: {ex}")

    st.session_state.last_run_at = datetime.now()

# --------------------------------------------------------------------
# Position panel - takes over the main view whenever one exists, instead
# of the normal scan/recommendation snapshot below.
# --------------------------------------------------------------------

if position is not None:

    snap = position["decision_snapshot"]
    status = position["status"]

    st.divider()
    st.subheader(f"📌 Position - {position['instrument']} ({position['mode']} mode)")

    cols = st.columns(4)
    cols[0].metric("Direction", position["direction"])
    cols[1].metric("Quantity", position["quantity"])
    cols[2].metric("Stop Loss (Nifty)", snap.get("stop_loss") or "-")
    cols[3].metric("Target 1 (Nifty)", snap.get("target_1") or "-")

    if status == position_store.PENDING_ENTRY_APPROVAL:

        st.info(
            f"Engine + Claude confirmed **{position['direction']}** at "
            f"**{position['instrument']}**, premium ~{snap.get('premium')}. "
            f"Approve to place a **{position['quantity']}**-quantity "
            f"{'live' if position['mode'] == 'live' else 'paper'} order."
        )
        st.caption(" · ".join(snap.get("reasons", [])))

        created_at = position.get("created_at")

        if created_at:
            created_dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
            elapsed_seconds = (datetime.now() - created_dt).total_seconds()
            minutes, seconds = divmod(int(elapsed_seconds), 60)
            hours, minutes = divmod(minutes, 60)
            age = (f"{hours}h {minutes}m ago" if hours else
                   f"{minutes}m {seconds}s ago" if minutes else
                   f"{seconds}s ago")

            if elapsed_seconds >= config.PENDING_ENTRY_STALE_SECONDS:
                st.warning(
                    f"⚠️ Proposed at **{created_at}** ({age}). The market has NOT been "
                    f"re-scanned since - this app stops scanning entirely while a position "
                    f"is pending approval. Price and premium above may no longer reflect "
                    f"current conditions - verify before approving, or Reject to get a "
                    f"fresh scan."
                )
            else:
                st.caption(f"Proposed at {created_at} ({age})")

        c1, c2 = st.columns(2)

        if c1.button("✅ Approve Entry", type="primary"):
            pipeline.approve_entry(position)
            st.rerun()

        if c2.button("❌ Reject"):
            pipeline.reject_entry(position)
            st.rerun()

    elif status == position_store.ENTRY_SUBMITTING:
        st.info("Submitting entry order...")

    elif status == position_store.ENTRY_ORDER_PLACED:
        placed_at = position.get("entry_order_placed_at")
        elapsed = (
            (datetime.now() - datetime.strptime(placed_at, "%Y-%m-%d %H:%M:%S")).total_seconds()
            if placed_at else None
        )

        if elapsed is not None and elapsed >= config.ENTRY_ORDER_TIMEOUT_SECONDS:
            st.warning(
                f"Entry order {position.get('entry_order_id')} still unfilled after "
                f"{int(elapsed)}s - the limit price may have already been missed by the market."
            )
            st.caption(
                "Cancelling closes this proposal out entirely (logged as a no-fill) rather than "
                "re-submitting the same setup at a new price - the next cycle re-evaluates the "
                "market from scratch and may propose a different trade."
            )
            if st.button("Cancel & Re-evaluate"):
                pipeline.cancel_stale_entry(position)
                st.rerun()
        else:
            st.info(f"Entry order {position.get('entry_order_id')} submitted - waiting for fill confirmation...")

    elif status == position_store.ENTRY_ORDER_FAILED:
        st.error(f"Entry order failed: {position.get('error')}")
        c1, c2 = st.columns(2)
        if c1.button("Retry Entry"):
            position_store.transition(position, position_store.ENTRY_ORDER_FAILED, position_store.PENDING_ENTRY_APPROVAL)
            st.rerun()
        if c2.button("Dismiss"):
            position_store.close_position(position, exit_price=None, exit_reason="ENTRY_FAILED")
            st.rerun()

    elif status == position_store.OPEN:

        eval_to_show = position_evaluation or st.session_state.get("last_position_evaluation")

        entry_price = position.get("entry_price")
        current_price = (position_market or {}).get("price")

        try:
            ltp = pipeline.get_current_premium(position)
        except Exception:
            ltp = None

        pnl_per_unit = round(ltp - entry_price, 2) if ltp is not None and entry_price is not None else None
        pnl_total = round(pnl_per_unit * position["quantity"], 2) if pnl_per_unit is not None else None
        pct_change = (
            round(pnl_per_unit / entry_price * 100, 2)
            if pnl_per_unit is not None and entry_price else None
        )

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Product", position.get("product_type") or "-")
        c2.metric("Avg Price", entry_price)
        c3.metric("LTP", ltp if ltp is not None else "-")
        c4.metric(
            "P&L",
            f"₹{pnl_total}" if pnl_total is not None else "-",
            f"{pct_change}%" if pct_change is not None else None,
        )

        c5, c6 = st.columns(2)
        c5.metric("Current Nifty Price", current_price if current_price is not None else "-")
        c6.metric(
            "Monitor Call",
            eval_to_show["action"] if eval_to_show else "-",
            eval_to_show.get("reason") if eval_to_show else None,
        )

        if position.get("exit_managed_by_broker"):
            st.caption(
                f"🔒 Protected by a Dhan Bracket Order - SL (-{config.BO_STOP_LOSS_POINTS} pts premium) "
                f"and Target (+{config.BO_PROFIT_POINTS} pts premium) are resting with the broker, "
                f"no approval click needed for either. This page will pick up the close automatically "
                f"once one fires."
            )
            st.caption(
                "Exiting manually below cancels those resting legs first, then places the "
                "square-off sell - if the legs can't be confidently identified/cancelled, the "
                "exit is refused rather than risking a duplicate order (check Dhan's app "
                "directly in that case)."
            )
        elif position.get("bo_fallback"):
            st.warning(
                "⚠️ Dhan rejected the Bracket Order for this entry (likely BO temporarily "
                "disabled for this contract/segment) - this entered as a **plain order with "
                "no automatic Stop Loss / Target**. Add SL/Target manually in Dhan's app, or "
                "this position relies entirely on this page's own monitor + Approve Exit to close."
            )

        if st.button("Exit Now (manual)"):
            pipeline.request_exit(position, "MANUAL_EXIT_REQUESTED")
            st.rerun()

    elif status == position_store.PENDING_EXIT_APPROVAL:

        st.warning(f"Exit recommended - reason: **{position.get('exit_reason')}**")

        c1, c2 = st.columns(2)

        if c1.button("✅ Approve Exit", type="primary"):
            pipeline.approve_exit(position)
            st.rerun()

        if c2.button("⏸ Hold anyway"):
            pipeline.hold_exit(position)
            st.rerun()

    elif status == position_store.EXIT_SUBMITTING:
        st.info("Submitting exit order...")

    elif status == position_store.EXIT_ORDER_PLACED:
        st.info(f"Exit order {position.get('exit_order_id')} submitted - waiting for fill confirmation...")

    elif status == position_store.EXIT_ORDER_FAILED:
        st.error(f"Exit order failed: {position.get('error')}")
        st.caption("This position is still open on Dhan - check Dhan's terminal and retry manually if needed.")
        if st.button("Retry Exit"):
            position_store.transition(position, position_store.EXIT_ORDER_FAILED, position_store.PENDING_EXIT_APPROVAL)
            st.rerun()

# --------------------------------------------------------------------
# Latest scan snapshot - only relevant when there's no active position
# --------------------------------------------------------------------

if position is None:

    if decision:
        recommendation = decision["recommendation"]
        last_run_at = st.session_state.last_run_at.strftime("%H:%M:%S")

        if recommendation == "BUY CALL":
            st.success(f"### 🟢 BUY CALL (AI-confirmed)  (as of {last_run_at})")
        elif recommendation == "BUY PUT":
            st.error(f"### 🔴 BUY PUT (AI-confirmed)  (as of {last_run_at})")
        else:
            st.info(f"### ⏳ WAIT  (as of {last_run_at})")

        engine_rec = decision.get("engine_recommendation")

        if engine_rec and engine_rec != recommendation:
            reasons_text = "; ".join(decision.get("reasons", []))

            if "skipped AI call" in reasons_text:
                st.warning(
                    f"Engine proposed **{engine_rec}**, but Claude wasn't consulted - no confirmed "
                    f"breakout (setups like this have historically always been rejected, so the "
                    f"paid call was skipped) — downgraded to WAIT."
                )
            elif "AI advisor unavailable" in reasons_text:
                st.error(
                    f"Engine proposed **{engine_rec}**, but the **Claude API call actually failed** "
                    f"— downgraded to WAIT without a real review. See logs/ai_advisor_errors.log "
                    f"for the traceback."
                )
            else:
                st.warning(
                    f"Engine proposed **{engine_rec}**, but Claude's verdict was "
                    f"**{decision.get('ai_verdict') or 'unavailable'}** — downgraded to WAIT."
                )

        trade = decision.get("selected_trade")

        cols = st.columns(4)
        cols[0].metric("Confidence", decision.get("confidence"))
        cols[1].metric("Instrument", trade["instrument"] if trade else "-")
        cols[2].metric("Premium", trade["premium"] if trade else "-")
        cols[3].metric("PCR", decision.get("pcr"))

        if recommendation in ("BUY CALL", "BUY PUT"):
            sl_cols = st.columns(3)
            sl_cols[0].metric("Stop Loss (Nifty)", decision.get("stop_loss") or "-")
            sl_cols[1].metric("Target 1 (Nifty)", decision.get("target_1") or "-")
            sl_cols[2].metric("Target 2 (Nifty)", decision.get("target_2") or "-")

        col_market, col_chain = st.columns(2)

        with col_market:
            st.subheader("Market")
            st.table(pd.DataFrame([{
                "Trend": market["trend"],
                "Momentum": market["momentum"],
                "1-min Momentum": decision["short_term_momentum"],
                "Price": market["price"],
                "EMA20": market["ema20"],
                "EMA50": market["ema50"],
                "VWAP": market["vwap"],
            }]).T.rename(columns={0: "Value"}).astype(str))

        with col_chain:
            st.subheader("Option Chain")
            st.table(pd.DataFrame([{
                "PCR": decision["pcr"],
                "OI Signal": decision["oi_signal"],
                "Support": decision["support"],
                "Resistance": decision["resistance"],
            }]).T.rename(columns={0: "Value"}).astype(str))

        st.subheader("Reasons")
        st.write(" · ".join(decision["reasons"]))

    else:
        st.info("Click **Run Now** in the sidebar to run the first cycle.")

    advice = signal_store.read_last_advice()
    if advice:
        advice_time = signal_store.read_last_advice_time()
        st.subheader("AI Advisor (Claude)")
        if advice_time:
            st.caption(
                f"Last checked by Claude at {advice_time} - Claude is only consulted "
                f"when the engine proposes an actual BUY CALL/PUT, so this may be from "
                f"an earlier cycle than the live snapshot above."
            )
        st.markdown(advice)

# --------------------------------------------------------------------
# Buy signals today
# --------------------------------------------------------------------

st.divider()
st.subheader("📈 Buy Signals Today")

rows = signal_store.load_today()

if rows:
    df = pd.DataFrame(rows).iloc[::-1].reset_index(drop=True)

    def highlight_row(row):
        color = "#d4f7d4" if row["recommendation"] == "BUY CALL" else "#f7d4d4"
        return [f"background-color: {color}"] * len(row)

    st.dataframe(df.style.apply(highlight_row, axis=1), width="stretch")
else:
    st.caption("No buy signals yet today.")

# --------------------------------------------------------------------
# Closed trades history
# --------------------------------------------------------------------

st.divider()
st.subheader("✅ Closed Trades")

closed = position_store.load_history()

if closed:
    st.dataframe(pd.DataFrame(closed).iloc[::-1].reset_index(drop=True), width="stretch")
else:
    st.caption("No closed trades yet.")

# --------------------------------------------------------------------
# Non-blocking auto-refresh (full page reload; session_state survives it)
# --------------------------------------------------------------------

if auto_refresh:
    st.markdown(
        f'<meta http-equiv="refresh" content="{int(interval)}">',
        unsafe_allow_html=True,
    )

"""
Local web UI for the analysis pipeline (replaces watching run_loop.py in a
terminal). Each page load/auto-refresh runs one pipeline.analyze() cycle,
same as run_loop.py; Claude is only asked to narrate when the recommendation
changes, also same as run_loop.py. BUY CALL / BUY PUT signals are appended
to a today-dated CSV (via signal_store) so they stay visible in a dedicated,
highlighted table until end of day regardless of page reloads.

Usage:
    streamlit run webapp.py
"""

from datetime import datetime

import pandas as pd
import streamlit as st

from pipeline import analyze, confirm_with_ai
import signal_store
import run_logger

st.set_page_config(page_title="AI Nifty Options Assistant", layout="wide")

signal_store.cleanup_old_files()

st.title("AI Nifty Options Buying Assistant")

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

if "session_has_run" not in st.session_state:
    st.session_state.session_has_run = False

should_run = run_now or auto_refresh or not st.session_state.session_has_run

market = option_result = decision = None

if should_run:
    st.session_state.session_has_run = True

    try:
        with st.spinner("Fetching Dhan data and running decision engine..."):
            market, option_result, decision = analyze()
    except Exception as ex:
        st.error(f"Cycle failed: {ex}")
    else:
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

            final_instrument = (
                (decision.get("selected_trade") or {}).get("instrument")
                if recommendation in ("BUY CALL", "BUY PUT") else None
            )

            signal_store.write_last_recommendation(recommendation)
            signal_store.write_last_instrument(final_instrument)

        run_logger.log_cycle(market, option_result, decision, engine_recommendation=engine_recommendation)

        st.session_state.last_run_at = datetime.now()

# --------------------------------------------------------------------
# Latest snapshot
# --------------------------------------------------------------------

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
    st.subheader("AI Advisor (Claude)")
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
# Non-blocking auto-refresh (full page reload; session_state survives it)
# --------------------------------------------------------------------

if auto_refresh:
    st.markdown(
        f'<meta http-equiv="refresh" content="{int(interval)}">',
        unsafe_allow_html=True,
    )

"""
Nifty OI Unwind Monitor
------------------------
Polls the option chain every ~3 seconds (Dhan's rate limit), tracks
'Chg in OI' at key strikes around spot, and flags when a strike shows
meaningful, sustained unwinding (a real signal) vs. normal fluctuation (noise).

Setup:
    pip install Dhan-Tradehull

Auth: set these as environment variables (client ID + daily access token,
regenerate the token from Dhan Web > Profile > DhanHQ Trading APIs):
    DHAN_CLIENT_ID
    DHAN_ACCESS_TOKEN

Run:
    python nifty_oi_monitor.py
"""

import os
import time
from collections import deque
from datetime import datetime

from Dhan_Tradehull import Tradehull

# ----------------------------- CONFIG -----------------------------

UNDERLYING = "NIFTY"
EXCHANGE = "NSE"
STRIKE_RANGE = 3          # ATM +/- N strikes to track
POLL_INTERVAL_SEC = 15    # OI updates slower than price; polling too fast just re-fetches the same value
HISTORY_LEN = 10          # how many polls to keep per strike (rolling window)

# Thresholds for flagging a "real" unwind (tune as you observe live behavior)
MIN_CONSECUTIVE_DECLINES = 3   # window size (in polls) to evaluate the trend over
UNWIND_PCT_THRESHOLD = 5.0     # min % decline in Chg in OI over the window to call it real

# --------------------------------------------------------------------


def connect():
    tsl = Tradehull(
        ClientCode=os.getenv("DHAN_CLIENT_ID"),
        token_id=os.getenv("DHAN_ACCESS_TOKEN"),
    )
    return tsl


def get_option_chain_snapshot(tsl):
    """
    Returns (atm_strike, df) where df has columns:
    'CE OI', 'CE Chg in OI', 'CE Volume', 'CE IV', 'CE LTP', ...,
    'Strike Price', ..., 'PE LTP', 'PE IV', 'PE Volume', 'PE Chg in OI', 'PE OI', ...
    """
    atm_strike, df = tsl.get_option_chain(
        Underlying=UNDERLYING,
        exchange="INDEX",
        expiry=0,
        num_strikes=STRIKE_RANGE,
    )
    return atm_strike, df


def track_and_flag(history, strike, side, chg_in_oi):
    """
    IMPORTANT: Dhan's 'Chg in OI' is cumulative from the start of the
    session, not a poll-to-poll delta. A strike can show real, sustained
    unwinding (OI falling poll after poll) while 'Chg in OI' itself stays
    positive all day (e.g. 6.9M -> 5.4M -> 4.1M -> 3.8M is a real ~45%
    unwind, even though every single value is positive).

    So we track the RAW 'Chg in OI' value across polls and look at the
    poll-over-poll DELTA (is it currently rising or falling), not the sign
    of the value itself.

    history: dict[(strike, side)] -> deque of past raw 'Chg in OI' values
    Flags when the raw value has been falling across most of the recent
    polls (majority-negative deltas, with tolerance for a noisy uptick)
    AND has fallen meaningfully over the whole window -- that's a real,
    sustained unwind, not just noise.
    """
    key = (strike, side)
    if key not in history:
        history[key] = deque(maxlen=HISTORY_LEN)

    hist = history[key]
    hist.append(chg_in_oi)

    if len(hist) < MIN_CONSECUTIVE_DECLINES + 1:
        return None

    recent = list(hist)[-(MIN_CONSECUTIVE_DECLINES + 1):]

    # Poll-over-poll deltas: negative means OI shrank since the last poll
    deltas = [recent[i + 1] - recent[i] for i in range(len(recent) - 1)]
    negative_deltas = sum(1 for d in deltas if d < 0)

    # Overall change across the whole window (start -> end of this run)
    total_change = recent[-1] - recent[0]
    pct_change = (total_change / abs(recent[0])) * 100 if recent[0] != 0 else 0

    # Majority of polls trending down (tolerate one noisy uptick) AND a
    # meaningful overall decline over the window -- that's a real unwind.
    majority_declining = negative_deltas >= (len(deltas) - 1)  # at most 1 non-decline allowed
    meaningful_decline = pct_change <= -UNWIND_PCT_THRESHOLD

    if majority_declining and meaningful_decline:
        return (f"UNWIND CONFIRMED: {strike} {side} Chg in OI falling "
                f"{pct_change:.1f}% over last {len(recent)} polls, latest={chg_in_oi:,.0f}")
    elif majority_declining:
        return (f"watch: {strike} {side} Chg in OI trending down "
                f"({pct_change:.1f}% so far), latest={chg_in_oi:,.0f}")
    return None


def main():
    tsl = connect()
    history = {}

    print(f"Starting Nifty OI monitor at {datetime.now().strftime('%H:%M:%S')}")
    print(f"Polling every {POLL_INTERVAL_SEC}s, tracking ATM +/- {STRIKE_RANGE} strikes\n")

    while True:
        try:
            atm_strike, df = get_option_chain_snapshot(tsl)

            poll_time = datetime.now().strftime('%H:%M:%S')
            print(f"[{poll_time}] poll ok | ATM={atm_strike} | strikes tracked={len(df)}")
            for _, row in df.iterrows():
                s = row.get("Strike Price")
                ce_c = row.get("CE Chg in OI")
                pe_c = row.get("PE Chg in OI")
                print(f"    strike={s}  CE Chg={ce_c:>10,.0f}  PE Chg={pe_c:>10,.0f}")

            for _, row in df.iterrows():
                strike = row.get("Strike Price")
                ce_chg = row.get("CE Chg in OI")
                pe_chg = row.get("PE Chg in OI")

                if ce_chg is not None:
                    flag = track_and_flag(history, strike, "CE", ce_chg)
                    if flag:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] ATM={atm_strike} {flag}")

                if pe_chg is not None:
                    flag = track_and_flag(history, strike, "PE", pe_chg)
                    if flag:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] ATM={atm_strike} {flag}")

            time.sleep(POLL_INTERVAL_SEC)

        except Exception as e:
            print(f"Error polling option chain: {e}")
            time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()
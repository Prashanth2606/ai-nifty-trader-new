"""
Repeatedly runs the analysis pipeline on a fixed interval and prints output.

Dhan calls happen every cycle (cheap/unlimited per user). The Claude advisor
call is the expensive part, so it only fires when decision['recommendation']
actually changes from the previous cycle (e.g. WAIT -> BUY CALL, or
BUY CALL -> WAIT) instead of on every single poll.

Usage:
    python run_loop.py            # every 20 seconds (default)
    python run_loop.py 30         # every 30 seconds

Press Ctrl+C to stop.
"""

import sys
import time
from datetime import datetime

from pipeline import analyze, narrate
import run_logger

INTERVAL_SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 20

last_recommendation = None
last_instrument = None

while True:

    started_at = time.monotonic()

    print("\n" + "#" * 70)
    print(f"# RUN AT {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("#" * 70)

    try:
        market, option_result, decision = analyze()

        engine_recommendation = decision.get("recommendation")
        engine_instrument = (decision.get("selected_trade") or {}).get("instrument")

        # Re-confirm whenever the proposal OR the underlying strike changes -
        # comparing the label alone would miss the engine flipping strikes
        # (e.g. 24000 PE -> 24200 PE) while still saying "BUY PUT".
        if engine_recommendation != last_recommendation or engine_instrument != last_instrument:
            print(f"\n[run_loop] signal changed "
                  f"({last_recommendation}/{last_instrument} -> {engine_recommendation}/{engine_instrument}), "
                  f"asking Claude to confirm")
            decision = narrate(market, option_result, decision)
        else:
            print("\n" + "=" * 70)
            print("AI TRADE ADVISOR (CLAUDE)")
            print("=" * 70)
            print("(unchanged since last cycle, skipped to save Claude API calls)")

        # Track the AI-gated recommendation, not the raw engine proposal,
        # so a Claude-rejected BUY doesn't get silently re-shown as final.
        last_recommendation = decision.get("recommendation")
        last_instrument = (
            (decision.get("selected_trade") or {}).get("instrument")
            if last_recommendation in ("BUY CALL", "BUY PUT") else None
        )

        run_logger.log_cycle(market, option_result, decision, engine_recommendation=engine_recommendation)

    except Exception as ex:
        print(f"\n[run_loop] cycle failed: {ex}")

    elapsed = time.monotonic() - started_at
    sleep_for = max(0.0, INTERVAL_SECONDS - elapsed)

    try:
        time.sleep(sleep_for)
    except KeyboardInterrupt:
        print("\n[run_loop] stopped by user")
        break

"""
File-based persistence for BUY CALL / BUY PUT signals fired during the day.

Signals for today live in signals/<YYYY-MM-DD>.csv. A small state file
(signals/.state.json) tracks the last recommendation seen and the last
Claude narration, so "only act on change" logic survives a Streamlit
session reset (e.g. the auto-refresh page reload), not just an in-memory
variable. Everything is scoped to the current date; files from a previous
day are removed the next time cleanup_old_files() runs (called on app
startup), which is the "deleted by EOD" behavior.
"""

import csv
import glob
import json
import os
from datetime import date, datetime

SIGNALS_DIR = "signals"
STATE_FILE = os.path.join(SIGNALS_DIR, ".state.json")

FIELDNAMES = [
    "time", "recommendation", "instrument", "premium", "confidence",
    "trend", "momentum", "short_term_momentum", "price", "ema20", "ema50",
    "vwap", "pcr", "oi_signal", "support", "resistance",
    "stop_loss", "target_1", "target_2", "reasons",
]


def _today_file():
    os.makedirs(SIGNALS_DIR, exist_ok=True)
    return os.path.join(SIGNALS_DIR, f"{date.today().isoformat()}.csv")


def cleanup_old_files():
    """Removes signal files (and state) left over from previous days."""

    os.makedirs(SIGNALS_DIR, exist_ok=True)

    today_file = _today_file()

    for path in glob.glob(os.path.join(SIGNALS_DIR, "*.csv")):
        if path != today_file:
            os.remove(path)

    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
        if state.get("date") != date.today().isoformat():
            os.remove(STATE_FILE)


def load_today():
    path = _today_file()
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def append_signal(row):
    path = _today_file()
    is_new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def clear_today():
    path = _today_file()
    if os.path.exists(path):
        os.remove(path)
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)


def _read_state():
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, encoding="utf-8") as f:
        state = json.load(f)
    if state.get("date") != date.today().isoformat():
        return {}
    return state


def _write_state(**updates):
    state = _read_state()
    state["date"] = date.today().isoformat()
    state.update(updates)
    os.makedirs(SIGNALS_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


def read_last_recommendation():
    return _read_state().get("last_recommendation")


def write_last_recommendation(recommendation):
    _write_state(last_recommendation=recommendation)


def read_last_instrument():
    return _read_state().get("last_instrument")


def write_last_instrument(instrument):
    _write_state(last_instrument=instrument)


def read_last_advice():
    return _read_state().get("last_advice")


def read_last_advice_time():
    return _read_state().get("last_advice_time")


def write_last_advice(advice):
    _write_state(
        last_advice=advice,
        last_advice_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

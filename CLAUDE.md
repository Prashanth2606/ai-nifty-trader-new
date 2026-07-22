# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-shot (not continuously running) Nifty index options analysis tool. It pulls historical
index candles and the live option chain from Dhan (Indian broker API), runs them through a
deterministic rule-based decision engine, and optionally asks Claude to explain (never override)
the resulting recommendation. There is no backtester and no automated (unattended) order
placement — running `app.py` performs one analysis pass and prints results.

`webapp.py` (Streamlit) additionally supports approval-gated order placement: an AI-confirmed
BUY CALL/PUT becomes a pending position that requires an explicit "Approve Entry" click before any
order is placed, and an open position's exit (stop-loss/target hit) likewise requires an explicit
"Approve Exit" click. No order is ever placed without that click — see "Position lifecycle" below.

## Setup & running

Python 3.14, venv at `.venv/`. No test framework, linter, or build step is configured.

```
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Requires a `.env` file (see `config.py`) with `DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN`, `CLAUDE_API_KEY`.

**`requirements.txt` is UTF-16 encoded** — if `pip install -r requirements.txt` fails to parse it,
re-save the file as UTF-8 before installing.

There are no automated tests. `test_history.py`, `debug_history.py`, and `market/debug_history.py`
are ad-hoc manual scripts (run directly with `python <file>.py`) for eyeballing candle data, not a
test suite — `market/debug_history.py` and root `debug_history.py` are identical duplicates.

## Architecture

`app.py` wires together a fixed pipeline, each stage a stateless class instantiated fresh per run:

```
HistoricalDataProvider.get_5min_candles() → candles (list of OHLCV dicts)
  → MarketAnalyzer.analyze()              → market dict (trend/momentum/EMA/VWAP/score)

HistoricalDataProvider.get_1min_candles() → candles_1m (list of OHLCV dicts)
  → MarketAnalyzer.analyze_1min_momentum() → short_term dict (short-term momentum, ~10 min lookback)

OptionChain.get_raw_chain()            → raw Dhan chain response
OptionChain.get_nearby_strikes()       → strikes around spot (±5 by default)
  → OptionChainAnalyzer.analyze()      → option_result dict (PCR/OI signal/support/resistance/ranked strikes)

DecisionEngine.decide(market, option_result, short_term) → decision dict (recommendation/confidence/selected_trade)

AIAdvisor.get_advice(market, option_result, decision) → Claude's prose explanation
```

**1-min data is a confirmation filter, not an independent signal.** `MarketAnalyzer.analyze_1min_momentum()`
runs the same move-based momentum classification as the 5-min `analyze()` but over the last 10 1-min
candles (~10 min) with smaller thresholds. `DecisionEngine.decide()` folds it into the bullish/bearish
score and, more importantly, requires it to agree with the trade direction (`BULLISH`/`STRONG_BULLISH`
for `BUY CALL`, `BEARISH`/`STRONG_BEARISH` for `BUY PUT`) before firing a recommendation — a strong
5-min setup with sideways/opposing 1-min momentum resolves to `WAIT`. `short_term` is optional
(`decide()` defaults it to `SIDEWAYS` if omitted).

Every stage passes plain dicts, not shared model objects — `models/market_snapshot.py` defines a
`MarketSnapshot` dataclass but nothing currently constructs or consumes it.

**All Dhan API access goes through `broker/dhan_client.py:get_dhan_client()`**, which builds a
`dhanhq` client from `DhanContext` using `config.py` credentials. Every provider class
(`HistoricalDataProvider`, `OptionChain`, `MarketDataProvider`) calls this in `__init__` rather than
sharing a client instance.

**The decision logic is intentionally rule-based, not LLM-driven.** `DecisionEngine.decide()` scores
bullish/bearish signals from trend, EMA20/50, VWAP (weighted highest), PCR, and OI-writing signal,
then applies fixed all-must-match conditions for `BUY CALL` / `BUY PUT`; anything else is `WAIT`.
`AIAdvisor` builds a prompt that explicitly forbids Claude from changing or inventing data — its
job is only to narrate the engine's own output in a fixed format (Recommendation/Summary/Strike/
Entry/SL/Targets/Confidence/Risk/Reasoning). When modifying trade logic, change `DecisionEngine`;
don't try to steer outcomes through the AI advisor prompt.

**Config values requiring manual upkeep**: `config.py`'s `EXPIRY` (option expiry date) must be
updated weekly to match the current Nifty weekly expiry; `OptionChain.get_raw_chain()` hardcodes
`expiry="2026-07-21"` directly rather than importing from `config.EXPIRY` — check both when the
expiry changes. `NIFTY_SECURITY_ID` (13) and `EXCHANGE` ("IDX_I") are Dhan-specific constants for
the Nifty 50 index. `config.py`'s `LOT_SIZE` (65 as of 2026-07-17) must be kept in sync with NSE's
current Nifty lot size — `broker/order_manager.py` cross-checks it against Dhan's own security
master at order-placement time and refuses to place an order on a mismatch, but that only catches
a stale value, it doesn't fix it.

## Position lifecycle / order placement

`webapp.py` is the only place with an order-placement UI (`run_loop.py` stays analysis-only). When
`DecisionEngine` + Claude confirm a BUY CALL/PUT and no position is already open/pending,
`position_store.create_pending_entry()` freezes that decision (instrument, premium, stop_loss,
target_1/2) into a new file-based position record (`position/state.json`) with status
`PENDING_ENTRY_APPROVAL`. From there:

```
PENDING_ENTRY_APPROVAL --Approve--> (place order) --> OPEN
OPEN --stop_loss/target_1 hit (engine/position_monitor.py) or manual "Exit Now"--> PENDING_EXIT_APPROVAL
PENDING_EXIT_APPROVAL --Approve Exit--> (place order) --> closed (appended to position/closed_trades.csv)
```

Only `broker/order_manager.py` is allowed to call Dhan's order-placement endpoints
(`place_order`/`get_order_by_id`), gated by `config.TRADING_MODE` ("live" places real orders;
"paper" simulates an instant fill at the frozen/current premium and never even constructs an
authenticated Dhan client). `position_store.transition()` is an atomic compare-and-swap (temp file +
`os.replace`) that only applies a state change if the on-disk status still matches what the caller
expects — this is what stops a double-click or an auto-refresh race from placing two orders for one
approval. `engine/position_monitor.py` deliberately does NOT re-run `DecisionEngine` or call Claude;
it only checks the live Nifty price against the stop_loss/target_1 frozen in at entry.

`broker/security_master.py` resolves a strike + CE/PE + `config.EXPIRY` to the Dhan `security_id`
needed to place an order (the option-chain response used elsewhere has no security_id) via Dhan's
public scrip-master CSV, cached locally (`broker/.security_master_cache.csv`, gitignored) for up to
`config.SECURITY_MASTER_MAX_AGE_HOURS`.

**`app-Claude.py` is not a variant of `app.py`.** Despite the name, it's a standalone, independently
runnable OI-unwind polling monitor (infinite loop, ~15s poll interval) built on a different library
(`Dhan_Tradehull`, not in `requirements.txt`) and reads Dhan credentials from raw env vars rather
than `config.py`. It shares no code with the `app.py` pipeline.

`market/market_data.py`'s `MarketDataProvider.get_snapshot()` is a debug stub — it fetches the raw
chain, prints it, and returns `None`. It is not part of the `app.py` pipeline (which uses
`market/option_chain.py`'s `OptionChain` instead).

No package uses `__init__.py` — imports rely on Python's implicit namespace packages.

## Dhan option-chain data shape

Code across `market/option_chain.py` and `analysis/option_chain_analyzer.py` repeatedly indexes into
the raw Dhan response as `chain["data"]["data"]["oc"]`, a dict keyed by strike price formatted as a
6-decimal string (`f"{strike:.6f}"`), each value holding `"ce"`/`"pe"` dicts with `oi`,
`previous_oi`, `last_price`, `volume`, `implied_volatility`. Any new code reading the chain should
follow this same access pattern rather than assuming a flatter structure.

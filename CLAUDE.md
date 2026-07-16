# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-shot (not continuously running) Nifty index options analysis tool. It pulls historical
index candles and the live option chain from Dhan (Indian broker API), runs them through a
deterministic rule-based decision engine, and optionally asks Claude to explain (never override)
the resulting recommendation. There is no backtester, no order placement, and no persistence layer
— running `app.py` performs one analysis pass and prints results.

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
`expiry="2026-07-14"` directly rather than importing from `config.EXPIRY` — check both when the
expiry changes. `NIFTY_SECURITY_ID` (13) and `EXCHANGE` ("IDX_I") are Dhan-specific constants for
the Nifty 50 index.

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

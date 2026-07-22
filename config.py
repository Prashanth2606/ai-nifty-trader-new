from dotenv import load_dotenv
import os

# override=True: a stale DHAN_ACCESS_TOKEN/DHAN_CLIENT_ID set as an actual
# Windows environment variable would otherwise silently win over .env,
# since load_dotenv() doesn't overwrite existing env vars by default.
load_dotenv(override=True)

# Dhan
DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID")
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN")

# Claude
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")

# Market
EXCHANGE = "IDX_I"
NIFTY_SECURITY_ID = 13

# Update every week
EXPIRY = "2026-07-28"

# Order placement
# LOT_SIZE: NSE revises this periodically - verify against a current Dhan
# contract note before relying on it, same upkeep discipline as EXPIRY above.
LOT_SIZE = 65
PRODUCT_TYPE = "INTRADAY"        # maps to dhanhq.INTRA - used for exit/manual orders
EXCHANGE_SEGMENT_FNO = "NSE_FNO"  # maps to dhanhq.FNO / dhanhq.NSE_FNO
ORDER_TYPE = "MARKET"

# Bracket Order (BO) protective SL/target for live entries - Dhan manages
# both as resting child orders once the entry fills, so exit no longer
# depends on this app polling price or you clicking "Approve Exit" (see
# broker/order_manager.py place_entry_order / pipeline.py
# reconcile_external_close). Both values are OPTION PREMIUM points, not
# underlying Nifty index points like DecisionEngine's stop_loss/target_1 -
# Dhan's BO API only ever understands offsets on the traded contract's own
# price. BO_PROFIT_POINTS is a 2:1 reward:risk against the 15-point SL;
# adjust if you want a different ratio.
BO_PRODUCT_TYPE = "BO"           # maps to dhanhq.BO
BO_STOP_LOSS_POINTS = 15
BO_PROFIT_POINTS = 30

# If a BO entry LIMIT order hasn't filled within this many seconds, the UI
# surfaces a "still unfilled - cancel and retry?" prompt instead of silently
# waiting all day (DAY validity) on a stale order priced at a moment that's
# already passed.
ENTRY_ORDER_TIMEOUT_SECONDS = 45

# While a position sits at PENDING_ENTRY_APPROVAL, the app deliberately stops
# scanning the market entirely (see webapp.py) - so if you step away, nothing
# re-validates the setup no matter how long the gap. Past this many seconds
# since created_at, the UI shows a stale-signal warning (seen live on
# 2026-07-22: a PUT sat pending ~1h45m and price had already reached what was
# supposed to be Target 1, at a materially worse premium, by the time it was
# noticed).
PENDING_ENTRY_STALE_SECONDS = 120

# Safety: only "live" ever calls a real Dhan order-placement endpoint.
# broker/order_manager.py is the sole module gated by this - set to "paper"
# for a simulated-fill dry run of the approval/monitoring flow.
TRADING_MODE = os.getenv("TRADING_MODE", "live")

# Dhan's scrip master CSV (strike -> security_id lookup) is large and
# doesn't change intraday, so it's cached locally instead of re-downloaded
# every cycle.
SECURITY_MASTER_CACHE_PATH = "broker/.security_master_cache.csv"
SECURITY_MASTER_MAX_AGE_HOURS = 24
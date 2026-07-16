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
EXPIRY = "2026-07-21"
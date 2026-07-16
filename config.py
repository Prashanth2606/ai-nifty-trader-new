from dotenv import load_dotenv
import os

load_dotenv()

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
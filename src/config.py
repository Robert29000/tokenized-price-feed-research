import os
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

ETHERSCAN_API_URL = "https://api.etherscan.io/v2/api"
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")
CHAIN_ID = int(os.getenv("CHAIN_ID", "1"))
ETHERSCAN_MIN_INTERVAL = float(os.getenv("ETHERSCAN_MIN_INTERVAL", "0.35"))

# Chainlink 24/5 tokenized-equity aggregators (Ethereum mainnet).
FEEDS = {
    "NVDA": "0x74acdd8ca84ff6a9eb0814e7f000b4f33195152d",
    "GOOGL": "0x2a539061d701471c3835256f8ff982e81e9b4374",
    "TSLA": "0x47f0840acb50df9c3b9584017ef1a9560e777b88",
    "SPCX": "0x1d37422e15ee379549b0b8e2a47523d3ef5071a9",
}

ET = ZoneInfo("America/New_York")

# Session boundaries in ET, per https://docs.chain.link/data-feeds/tokenized-equity-feeds#session-coverage.
# Overnight [20:00, 04:00) belongs to the next trading day.
PRE_MARKET_START = time(4, 0)
REGULAR_START = time(9, 30)
POST_MARKET_START = time(16, 0)
OVERNIGHT_START = time(20, 0)

OPEN_SESSIONS = ["overnight", "pre_market", "regular", "post_market"]
CLOSED_SESSIONS = ["weekend", "holiday"]

DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"

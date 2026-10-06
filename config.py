import os

ALLOWED_ASSETS = ("BTC", "ETH", "GRAM")
STATE_DIR = os.getenv("STATE_DIR", "/workspace/data")

INITIAL_EQUITY = float(os.getenv("INITIAL_EQUITY", "100"))
NORMAL_POSITION_PCT = float(os.getenv("NORMAL_POSITION_PCT", "0.10"))
MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", "0.20"))
NORMAL_RISK_PCT = float(os.getenv("NORMAL_RISK_PCT", "0.02"))
HARD_RISK_PCT = float(os.getenv("HARD_RISK_PCT", "0.03"))
DAILY_LOSS_LIMIT_PCT = float(os.getenv("DAILY_LOSS_LIMIT_PCT", "0.06"))
MAX_DRAWDOWN_PCT = float(os.getenv("MAX_DRAWDOWN_PCT", "0.25"))
MAX_TOTAL_EXPOSURE_PCT = float(os.getenv("MAX_TOTAL_EXPOSURE_PCT", "0.30"))
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "2"))
DEFAULT_LEVERAGE = float(os.getenv("DEFAULT_LEVERAGE", "3"))
MAX_LEVERAGE = float(os.getenv("MAX_LEVERAGE", "5"))

STALE_MARKET_SECONDS = int(os.getenv("STALE_MARKET_SECONDS", "180"))
MIN_NEWS_SOURCE_SUCCESSES = int(os.getenv("MIN_NEWS_SOURCE_SUCCESSES", "2"))
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "900"))

NEWS_POLL_SECONDS = int(os.getenv("NEWS_POLL_SECONDS", "20"))
POSITION_POLL_SECONDS = int(os.getenv("POSITION_POLL_SECONDS", "15"))
DECISION_INTERVAL_SECONDS = int(os.getenv("DECISION_INTERVAL_SECONDS", "300"))
WORKER_TICK_SECONDS = int(os.getenv("WORKER_TICK_SECONDS", "2"))

AUTO_DECISION = os.getenv("AUTO_DECISION", "false").lower() == "true"
AUTO_PAPER_EXECUTION = os.getenv("AUTO_PAPER_EXECUTION", "true").lower() == "true"

PORT = int(os.getenv("PORT", "8080"))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-6-astra")
OPENAI_PROMPT_ID = os.getenv("OPENAI_PROMPT_ID", "").strip()
OPENAI_REASONING_EFFORT = os.getenv("OPENAI_REASONING_EFFORT", "medium")

MARKETTWITS_URL = os.getenv("MARKETTWITS_URL", "https://t.me/s/markettwits")

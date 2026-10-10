import os
ALLOWED_ASSETS=("BTC","ETH","GRAM")
STATE_DIR=os.getenv("STATE_DIR","/workspace/data")
INITIAL_EQUITY=float(os.getenv("INITIAL_EQUITY","100"))
NORMAL_POSITION_PCT=float(os.getenv("NORMAL_POSITION_PCT","0.10"))
MAX_POSITION_PCT=float(os.getenv("MAX_POSITION_PCT","0.20"))
NORMAL_RISK_PCT=float(os.getenv("NORMAL_RISK_PCT","0.02"))
HARD_RISK_PCT=float(os.getenv("HARD_RISK_PCT","0.03"))
DAILY_LOSS_LIMIT_PCT=float(os.getenv("DAILY_LOSS_LIMIT_PCT","0.06"))
MAX_DRAWDOWN_PCT=float(os.getenv("MAX_DRAWDOWN_PCT","0.25"))
MAX_TOTAL_EXPOSURE_PCT=float(os.getenv("MAX_TOTAL_EXPOSURE_PCT","0.30"))
MAX_OPEN_POSITIONS=int(os.getenv("MAX_OPEN_POSITIONS","2"))
DEFAULT_LEVERAGE=float(os.getenv("DEFAULT_LEVERAGE","3"))
MAX_LEVERAGE=float(os.getenv("MAX_LEVERAGE","5"))
STALE_MARKET_SECONDS=int(os.getenv("STALE_MARKET_SECONDS","180"))
MIN_NEWS_SOURCE_SUCCESSES=int(os.getenv("MIN_NEWS_SOURCE_SUCCESSES","2"))
COOLDOWN_SECONDS=int(os.getenv("COOLDOWN_SECONDS","900"))
NEWS_POLL_SECONDS=int(os.getenv("NEWS_POLL_SECONDS","20"))
POSITION_POLL_SECONDS=int(os.getenv("POSITION_POLL_SECONDS","10"))
DECISION_INTERVAL_SECONDS=int(os.getenv("DECISION_INTERVAL_SECONDS","3600"))
WORKER_TICK_SECONDS=int(os.getenv("WORKER_TICK_SECONDS","2"))
AUTO_DECISION=os.getenv("AUTO_DECISION","false").lower()=="true"
AUTO_PAPER_EXECUTION=os.getenv("AUTO_PAPER_EXECUTION","true").lower()=="true"
MODEL_GATE_MIN_SCORE=int(os.getenv("MODEL_GATE_MIN_SCORE","3"))
NEWS_BLOCK_MINUTES=int(os.getenv("NEWS_BLOCK_MINUTES","120"))
MAX_MODEL_NEWS_EVENTS=int(os.getenv("MAX_MODEL_NEWS_EVENTS","8"))
PORT=int(os.getenv("PORT","8080"))
OPENAI_API_KEY=os.getenv("OPENAI_API_KEY","").strip()
OPENAI_MODEL=os.getenv("OPENAI_MODEL","gpt-6-astra")
OPENAI_PROMPT_ID=os.getenv("OPENAI_PROMPT_ID","").strip()
OPENAI_REASONING_EFFORT=os.getenv("OPENAI_REASONING_EFFORT","low")
MARKETTWITS_URL=os.getenv("MARKETTWITS_URL","https://t.me/s/markettwits")
EXECUTION_MODE=os.getenv("EXECUTION_MODE","paper").strip().lower()
TRADING_TIMEFRAME=os.getenv("TRADING_TIMEFRAME","1h")
OKX_API_KEY=os.getenv("OKX_API_KEY","").strip()
OKX_API_SECRET=os.getenv("OKX_API_SECRET","").strip()
OKX_API_PASSPHRASE=os.getenv("OKX_API_PASSPHRASE","").strip()
OKX_BASE_URL=os.getenv("OKX_BASE_URL","https://www.okx.com").rstrip("/")
OKX_TD_MODE=os.getenv("OKX_TD_MODE","isolated").strip()
TELEGRAM_ENABLED=os.getenv("TELEGRAM_ENABLED","false").lower()=="true"
TELEGRAM_BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN","").strip()
TELEGRAM_CHAT_ID=os.getenv("TELEGRAM_CHAT_ID","").strip()

# Trade-quality / exchange-protection rules
MIN_TP1_R = float(os.getenv("MIN_TP1_R", "1.0"))
MIN_TP2_R = float(os.getenv("MIN_TP2_R", "1.8"))
ONE_POSITION_PER_ASSET = os.getenv("ONE_POSITION_PER_ASSET", "true").lower() == "true"
EXCHANGE_SIDE_TP_SL = os.getenv("EXCHANGE_SIDE_TP_SL", "true").lower() == "true"

MOVE_SL_TO_BREAKEVEN_AFTER_TP1 = os.getenv("MOVE_SL_TO_BREAKEVEN_AFTER_TP1", "true").lower() == "true"

# Entry-quality guards
SHORT_CHASE_RSI = float(os.getenv("SHORT_CHASE_RSI", "30"))
LONG_CHASE_RSI = float(os.getenv("LONG_CHASE_RSI", "70"))
CHASE_EXTREME_DISTANCE_PCT = float(os.getenv("CHASE_EXTREME_DISTANCE_PCT", "0.60"))
CHASE_IMPULSE_ATR_MULT = float(os.getenv("CHASE_IMPULSE_ATR_MULT", "1.20"))

# Correlated BTC/ETH exposure
BLOCK_BTC_ETH_SAME_DIRECTION = os.getenv("BLOCK_BTC_ETH_SAME_DIRECTION", "true").lower() == "true"

# Cooldown after an actual stop-loss
STOP_LOSS_COOLDOWN_SECONDS = int(os.getenv("STOP_LOSS_COOLDOWN_SECONDS", "3600"))
EMERGENCY_EXIT_COOLDOWN_SECONDS = int(os.getenv("EMERGENCY_EXIT_COOLDOWN_SECONDS", "3600"))

# Emergency position exit
EMERGENCY_EXIT_ENABLED = os.getenv("EMERGENCY_EXIT_ENABLED", "false").lower() == "true"
EXIT_MARKET_CHECK_SECONDS = int(os.getenv("EXIT_MARKET_CHECK_SECONDS", "30"))
EMERGENCY_MARKET_EXIT_SCORE = int(os.getenv("EMERGENCY_MARKET_EXIT_SCORE", "4"))
EMERGENCY_MARKET_IMMEDIATE_SCORE = int(os.getenv("EMERGENCY_MARKET_IMMEDIATE_SCORE", "6"))
EMERGENCY_MARKET_CONFIRMATIONS = int(os.getenv("EMERGENCY_MARKET_CONFIRMATIONS", "2"))
EMERGENCY_NEWS_MAX_AGE_MINUTES = int(os.getenv("EMERGENCY_NEWS_MAX_AGE_MINUTES", "30"))
EMERGENCY_NEWS_MIN_CONFIDENCE = float(os.getenv("EMERGENCY_NEWS_MIN_CONFIDENCE", "80"))

# ===== ASTRA MTF v2 =====
# 4H regime -> 1H setup -> 15M trigger
MTF_ENABLED = os.getenv("MTF_ENABLED", "true").lower() == "true"
MTF_MIN_QUALITY = float(os.getenv("MTF_MIN_QUALITY", "72"))
MTF_TRIGGER_MIN_COMPONENTS = int(os.getenv("MTF_TRIGGER_MIN_COMPONENTS", "3"))
ENTRY_DRIFT_MAX_PCT = float(os.getenv("ENTRY_DRIFT_MAX_PCT", "0.25"))

# Minimum model confidence. Confidence is NOT win probability.
MIN_TRADE_CONFIDENCE = float(os.getenv("MIN_TRADE_CONFIDENCE", "80"))

# Confidence/quality based risk tiers.
# Deterministic Risk Engine chooses the actual risk; ASTRA never sizes a trade.
RISK_PCT_80_84 = float(os.getenv("RISK_PCT_80_84", "0.0035"))
RISK_PCT_85_91 = float(os.getenv("RISK_PCT_85_91", "0.0050"))
RISK_PCT_92_PLUS = float(os.getenv("RISK_PCT_92_PLUS", "0.0075"))

# Dynamic leverage is technical/margin leverage only; max stays 5x.
LEVERAGE_HIGH_VOL = float(os.getenv("LEVERAGE_HIGH_VOL", "2"))
LEVERAGE_NORMAL = float(os.getenv("LEVERAGE_NORMAL", "3"))
LEVERAGE_BEST_SETUP = float(os.getenv("LEVERAGE_BEST_SETUP", "5"))
BEST_SETUP_MIN_QUALITY = float(os.getenv("BEST_SETUP_MIN_QUALITY", "90"))
BEST_SETUP_MIN_CONFIDENCE = float(os.getenv("BEST_SETUP_MIN_CONFIDENCE", "92"))
BEST_SETUP_MAX_STOP_PCT = float(os.getenv("BEST_SETUP_MAX_STOP_PCT", "1.50"))

# Pause new entries after a losing streak.
LOSS_STREAK_LIMIT = int(os.getenv("LOSS_STREAK_LIMIT", "3"))
LOSS_STREAK_PAUSE_SECONDS = int(os.getenv("LOSS_STREAK_PAUSE_SECONDS", "21600"))

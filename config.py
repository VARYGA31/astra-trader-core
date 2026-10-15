import os
ALLOWED_ASSETS=("BTC","ETH","GRAM","XAU")
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
MIN_TP1_R = float(os.getenv("MIN_TP1_R", "1.2"))
MIN_TP2_R = float(os.getenv("MIN_TP2_R", "2.0"))
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

# ===== XAU / Gold =====
# Gold uses a stricter MTF + macro filter than crypto.
XAU_MTF_MIN_QUALITY = float(os.getenv("XAU_MTF_MIN_QUALITY", "78"))
XAU_MIN_TRADE_CONFIDENCE = float(os.getenv("XAU_MIN_TRADE_CONFIDENCE", "84"))
XAU_WEEKEND_BLOCK = os.getenv("XAU_WEEKEND_BLOCK", "true").lower() == "true"
XAU_MACRO_PRIMARY_REQUIRED = os.getenv("XAU_MACRO_PRIMARY_REQUIRED", "true").lower() == "true"
XAU_NEWS_SETTLE_MINUTES = int(os.getenv("XAU_NEWS_SETTLE_MINUTES", "5"))

# Requested leverage range for XAU only.
# Leverage changes margin usage, NOT the allowed $ risk to the stop.
XAU_MIN_LEVERAGE = float(os.getenv("XAU_MIN_LEVERAGE", "5"))
XAU_NORMAL_LEVERAGE = float(os.getenv("XAU_NORMAL_LEVERAGE", "7"))
XAU_MAX_LEVERAGE = float(os.getenv("XAU_MAX_LEVERAGE", "10"))
XAU_BEST_SETUP_MIN_QUALITY = float(os.getenv("XAU_BEST_SETUP_MIN_QUALITY", "92"))
XAU_BEST_SETUP_MIN_CONFIDENCE = float(os.getenv("XAU_BEST_SETUP_MIN_CONFIDENCE", "94"))
XAU_BEST_SETUP_MAX_STOP_PCT = float(os.getenv("XAU_BEST_SETUP_MAX_STOP_PCT", "1.50"))


# ===== Passive observability / analytics =====
# These settings DO NOT change signals, risk, leverage, or execution.
OBSERVABILITY_ENABLED = os.getenv("OBSERVABILITY_ENABLED", "true").lower() == "true"
SHADOW_JOURNAL_ENABLED = os.getenv("SHADOW_JOURNAL_ENABLED", "true").lower() == "true"
SHADOW_MIN_QUALITY = float(os.getenv("SHADOW_MIN_QUALITY", "50"))
OBSERVABILITY_LOG_MAX_MB = float(os.getenv("OBSERVABILITY_LOG_MAX_MB", "20"))
ANALYTICS_RECENT_LIMIT = int(os.getenv("ANALYTICS_RECENT_LIMIT", "20"))


# ===== MTF Transition Mode =====
# Allows a conservative crypto setup while 4H is MIXED (never opposite),
# when 1H setup + strong 15M trigger are already confirmed. XAU is excluded.
MTF_TRANSITION_ENABLED = os.getenv("MTF_TRANSITION_ENABLED", "true").lower() == "true"
MTF_TRANSITION_MIN_QUALITY = float(os.getenv("MTF_TRANSITION_MIN_QUALITY", "60"))
MTF_TRANSITION_TRIGGER_MIN_COMPONENTS = int(os.getenv("MTF_TRANSITION_TRIGGER_MIN_COMPONENTS", "4"))
MTF_TRANSITION_MIN_CONFIDENCE = float(os.getenv("MTF_TRANSITION_MIN_CONFIDENCE", "90"))
MTF_TRANSITION_RISK_PCT = float(os.getenv("MTF_TRANSITION_RISK_PCT", "0.0030"))
MTF_TRANSITION_MIN_TP1_R = float(os.getenv("MTF_TRANSITION_MIN_TP1_R", "1.20"))
MTF_TRANSITION_MIN_TP2_R = float(os.getenv("MTF_TRANSITION_MIN_TP2_R", "2.00"))


# ===== Execution Quality / Fill Protection =====
# Entry orders use a price-bounded FOK limit instead of an unbounded market order.
# If the full size cannot fill within the allowed price/R:R boundary, no trade is opened.
EXECUTION_QUALITY_ENABLED = os.getenv("EXECUTION_QUALITY_ENABLED", "true").lower() == "true"
OKX_ENTRY_ORDER_TYPE = os.getenv("OKX_ENTRY_ORDER_TYPE", "fok").strip().lower()

# Maximum adverse entry slippage versus the live OKX swap reference immediately
# before submission. These do NOT loosen R:R; both conditions must pass.
CRYPTO_MAX_ENTRY_SLIPPAGE_PCT = float(os.getenv("CRYPTO_MAX_ENTRY_SLIPPAGE_PCT", "0.15"))
GRAM_MAX_ENTRY_SLIPPAGE_PCT = float(os.getenv("GRAM_MAX_ENTRY_SLIPPAGE_PCT", "0.20"))
XAU_MAX_ENTRY_SLIPPAGE_PCT = float(os.getenv("XAU_MAX_ENTRY_SLIPPAGE_PCT", "0.10"))

# If an impossible post-fill audit failure is detected, flatten immediately.
POST_FILL_FAILSAFE_CLOSE = os.getenv("POST_FILL_FAILSAFE_CLOSE", "true").lower() == "true"


# ===== Strategy Mode Controller / Telegram =====
# Runtime mode is persisted under STATE_DIR and can be changed from the authorized Telegram chat.
# NORMAL = existing 4H -> 1H -> 15M ASTRA strategy.
# SCALP  = separate 1H -> 15M -> 5M strategy.
# PAUSED = no new entries; position monitoring / protective exits continue.
DEFAULT_STRATEGY_MODE = os.getenv("DEFAULT_STRATEGY_MODE", "NORMAL").strip().upper()
TELEGRAM_CONTROL_ENABLED = os.getenv("TELEGRAM_CONTROL_ENABLED", "true").lower() == "true"
TELEGRAM_CONTROL_POLL_TIMEOUT = int(os.getenv("TELEGRAM_CONTROL_POLL_TIMEOUT", "20"))

# ===== ASTRA SCALP v1 =====
# First version is crypto-only. XAU remains available in NORMAL mode.
SCALP_ALLOWED_ASSETS = tuple(
    x.strip().upper() for x in os.getenv("SCALP_ALLOWED_ASSETS", "BTC,ETH,GRAM").split(",") if x.strip()
)
SCALP_DECISION_INTERVAL_SECONDS = int(os.getenv("SCALP_DECISION_INTERVAL_SECONDS", "60"))
SCALP_MIN_QUALITY = float(os.getenv("SCALP_MIN_QUALITY", "70"))
SCALP_TRIGGER_MIN_COMPONENTS = int(os.getenv("SCALP_TRIGGER_MIN_COMPONENTS", "4"))
SCALP_MIN_TRADE_CONFIDENCE = float(os.getenv("SCALP_MIN_TRADE_CONFIDENCE", "82"))
SCALP_NEWS_SETTLE_MINUTES = int(os.getenv("SCALP_NEWS_SETTLE_MINUTES", "10"))
SCALP_MAX_SPREAD_PCT = float(os.getenv("SCALP_MAX_SPREAD_PCT", "0.10"))
SCALP_MIN_ATR_PCT = float(os.getenv("SCALP_MIN_ATR_PCT", "0.08"))
SCALP_MAX_ATR_PCT = float(os.getenv("SCALP_MAX_ATR_PCT", "1.25"))
SCALP_VOLUME_MIN_RATIO = float(os.getenv("SCALP_VOLUME_MIN_RATIO", "0.75"))
SCALP_SHORT_CHASE_RSI = float(os.getenv("SCALP_SHORT_CHASE_RSI", "25"))
SCALP_LONG_CHASE_RSI = float(os.getenv("SCALP_LONG_CHASE_RSI", "75"))
SCALP_CHASE_IMPULSE_ATR_MULT = float(os.getenv("SCALP_CHASE_IMPULSE_ATR_MULT", "2.20"))

# Short-horizon target requirements. Still enforced again after the actual fill.
SCALP_MIN_TP1_R = float(os.getenv("SCALP_MIN_TP1_R", "1.0"))
SCALP_MIN_TP2_R = float(os.getenv("SCALP_MIN_TP2_R", "1.6"))
SCALP_MIN_STOP_PCT = float(os.getenv("SCALP_MIN_STOP_PCT", "0.08"))
SCALP_MAX_STOP_PCT = float(os.getenv("SCALP_MAX_STOP_PCT", "1.00"))

# Risk remains stop-based. Leverage changes margin usage, not the loss budget.
SCALP_RISK_PCT_82_86 = float(os.getenv("SCALP_RISK_PCT_82_86", "0.0035"))
SCALP_RISK_PCT_87_91 = float(os.getenv("SCALP_RISK_PCT_87_91", "0.0050"))
SCALP_RISK_PCT_92_PLUS = float(os.getenv("SCALP_RISK_PCT_92_PLUS", "0.0075"))
SCALP_HARD_RISK_PCT = float(os.getenv("SCALP_HARD_RISK_PCT", "0.0075"))
SCALP_LEVERAGE_HIGH_VOL = float(os.getenv("SCALP_LEVERAGE_HIGH_VOL", "3"))
SCALP_LEVERAGE_NORMAL = float(os.getenv("SCALP_LEVERAGE_NORMAL", "5"))
SCALP_LEVERAGE_BEST_SETUP = float(os.getenv("SCALP_LEVERAGE_BEST_SETUP", "7"))
SCALP_MAX_LEVERAGE = float(os.getenv("SCALP_MAX_LEVERAGE", "7"))
SCALP_BEST_SETUP_MIN_QUALITY = float(os.getenv("SCALP_BEST_SETUP_MIN_QUALITY", "90"))
SCALP_BEST_SETUP_MIN_CONFIDENCE = float(os.getenv("SCALP_BEST_SETUP_MIN_CONFIDENCE", "92"))
SCALP_STOP_LOSS_COOLDOWN_SECONDS = int(os.getenv("SCALP_STOP_LOSS_COOLDOWN_SECONDS", "900"))
SCALP_LOSS_STREAK_LIMIT = int(os.getenv("SCALP_LOSS_STREAK_LIMIT", "3"))
SCALP_LOSS_STREAK_PAUSE_SECONDS = int(os.getenv("SCALP_LOSS_STREAK_PAUSE_SECONDS", "3600"))


# ===== SCALP v2: PRIME + FAST =====
# PRIME keeps the original strict setup. FAST accepts a 3/5 5m trigger only
# when higher-timeframe alignment, volume and spread are stronger.
SCALP_FAST_ENABLED = os.getenv("SCALP_FAST_ENABLED", "true").lower() == "true"
SCALP_FAST_MIN_QUALITY = float(os.getenv("SCALP_FAST_MIN_QUALITY", "64"))
SCALP_FAST_TRIGGER_MIN_COMPONENTS = int(os.getenv("SCALP_FAST_TRIGGER_MIN_COMPONENTS", "3"))
SCALP_FAST_MIN_TRADE_CONFIDENCE = float(os.getenv("SCALP_FAST_MIN_TRADE_CONFIDENCE", "86"))
SCALP_FAST_VOLUME_MIN_RATIO = float(os.getenv("SCALP_FAST_VOLUME_MIN_RATIO", "0.90"))
SCALP_FAST_MAX_SPREAD_PCT = float(os.getenv("SCALP_FAST_MAX_SPREAD_PCT", "0.06"))
SCALP_FAST_MIN_1H_SCORE = int(os.getenv("SCALP_FAST_MIN_1H_SCORE", "3"))
SCALP_FAST_MIN_15M_SCORE = int(os.getenv("SCALP_FAST_MIN_15M_SCORE", "3"))
SCALP_FAST_MIN_TP1_R = float(os.getenv("SCALP_FAST_MIN_TP1_R", "1.0"))
SCALP_FAST_MIN_TP2_R = float(os.getenv("SCALP_FAST_MIN_TP2_R", "1.5"))
SCALP_FAST_RISK_PCT_BASE = float(os.getenv("SCALP_FAST_RISK_PCT_BASE", "0.0025"))
SCALP_FAST_RISK_PCT_BEST = float(os.getenv("SCALP_FAST_RISK_PCT_BEST", "0.0035"))
SCALP_FAST_BEST_MIN_QUALITY = float(os.getenv("SCALP_FAST_BEST_MIN_QUALITY", "80"))
SCALP_FAST_BEST_MIN_CONFIDENCE = float(os.getenv("SCALP_FAST_BEST_MIN_CONFIDENCE", "90"))
SCALP_FAST_HARD_RISK_PCT = float(os.getenv("SCALP_FAST_HARD_RISK_PCT", "0.0035"))
SCALP_FAST_LEVERAGE_HIGH_VOL = float(os.getenv("SCALP_FAST_LEVERAGE_HIGH_VOL", "2"))
SCALP_FAST_LEVERAGE_NORMAL = float(os.getenv("SCALP_FAST_LEVERAGE_NORMAL", "3"))
SCALP_FAST_MAX_LEVERAGE = float(os.getenv("SCALP_FAST_MAX_LEVERAGE", "3"))

# Persistent diagnostics used by /scalp_stats.
SCALP_STATS_LOG_MAX_MB = float(os.getenv("SCALP_STATS_LOG_MAX_MB", "10"))
SCALP_STATS_DEFAULT_HOURS = int(os.getenv("SCALP_STATS_DEFAULT_HOURS", "6"))


# ===== ASTRA ADAPTIVE v1 =====
# AUTO mode asks one multi-asset strategist to rank BTC/ETH/GRAM on each new
# confirmed 5m candle. Python risk/execution remains the final authority.
ADAPTIVE_ALLOWED_ASSETS = tuple(
    x.strip().upper() for x in os.getenv("ADAPTIVE_ALLOWED_ASSETS", "BTC,ETH,GRAM").split(",") if x.strip()
)
ADAPTIVE_DECISION_INTERVAL_SECONDS = int(os.getenv("ADAPTIVE_DECISION_INTERVAL_SECONDS", "60"))
ADAPTIVE_NEWS_HOURS = int(os.getenv("ADAPTIVE_NEWS_HOURS", "12"))
ADAPTIVE_MEMORY_EXAMPLES = int(os.getenv("ADAPTIVE_MEMORY_EXAMPLES", "6"))
ADAPTIVE_OUTCOME_HORIZONS_MINUTES = tuple(
    int(x.strip()) for x in os.getenv("ADAPTIVE_OUTCOME_HORIZONS_MINUTES", "15,30,60,120").split(",") if x.strip()
)
ADAPTIVE_OUTCOME_EVAL_BATCH = int(os.getenv("ADAPTIVE_OUTCOME_EVAL_BATCH", "24"))
ADAPTIVE_MISSED_MOVE_SCALP_PCT = float(os.getenv("ADAPTIVE_MISSED_MOVE_SCALP_PCT", "0.35"))
ADAPTIVE_MISSED_MOVE_NORMAL_PCT = float(os.getenv("ADAPTIVE_MISSED_MOVE_NORMAL_PCT", "0.90"))
ADAPTIVE_LOG_MAX_MB = float(os.getenv("ADAPTIVE_LOG_MAX_MB", "20"))

# Independent adaptive safety checks. These do not create signals; they only
# reject unsafe execution after the model proposes a trade.
ADAPTIVE_SCALP_MAX_SPREAD_PCT = float(os.getenv("ADAPTIVE_SCALP_MAX_SPREAD_PCT", "0.10"))
ADAPTIVE_NORMAL_MAX_SPREAD_PCT = float(os.getenv("ADAPTIVE_NORMAL_MAX_SPREAD_PCT", "0.18"))
ADAPTIVE_MIN_NORMAL_QUALITY = float(os.getenv("ADAPTIVE_MIN_NORMAL_QUALITY", "72"))
ADAPTIVE_MIN_SCALP_QUALITY = float(os.getenv("ADAPTIVE_MIN_SCALP_QUALITY", "64"))


# ===== ASTRA ADAPTIVE Cost-Smart v1 =====
# Local market scans stay on every new 5m candle, but expensive GPT-6 Astra
# calls are scheduled by baseline interval + opportunity triggers + daily caps.
ADAPTIVE_COST_SMART_ENABLED = os.getenv("ADAPTIVE_COST_SMART_ENABLED", "true").lower() == "true"
ADAPTIVE_BASE_MODEL_INTERVAL_MINUTES = int(os.getenv("ADAPTIVE_BASE_MODEL_INTERVAL_MINUTES", "90"))
ADAPTIVE_TRIGGER_MIN_GAP_MINUTES = int(os.getenv("ADAPTIVE_TRIGGER_MIN_GAP_MINUTES", "10"))
ADAPTIVE_TRIGGER_SCORE = float(os.getenv("ADAPTIVE_TRIGGER_SCORE", "4.0"))
ADAPTIVE_TRIGGER_5M_MOVE_PCT = float(os.getenv("ADAPTIVE_TRIGGER_5M_MOVE_PCT", "0.18"))
ADAPTIVE_TRIGGER_MAX_SPREAD_PCT = float(os.getenv("ADAPTIVE_TRIGGER_MAX_SPREAD_PCT", "0.08"))
ADAPTIVE_MAX_MODEL_CALLS_PER_DAY = int(os.getenv("ADAPTIVE_MAX_MODEL_CALLS_PER_DAY", "24"))
ADAPTIVE_MAX_ESTIMATED_USD_PER_DAY = float(os.getenv("ADAPTIVE_MAX_ESTIMATED_USD_PER_DAY", "2.50"))
# Keep a deterministic reserve for strong opportunities/news later in the UTC day.
ADAPTIVE_BASELINE_RESERVE_CALLS = int(os.getenv("ADAPTIVE_BASELINE_RESERVE_CALLS", "6"))
ADAPTIVE_BASELINE_RESERVE_USD = float(os.getenv("ADAPTIVE_BASELINE_RESERVE_USD", "0.80"))
ADAPTIVE_ESTIMATED_NEXT_CALL_USD = float(os.getenv("ADAPTIVE_ESTIMATED_NEXT_CALL_USD", "0.13"))
ADAPTIVE_MAX_NEWS_EVENTS = int(os.getenv("ADAPTIVE_MAX_NEWS_EVENTS", "4"))
ADAPTIVE_MODEL_MAX_OUTPUT_TOKENS = int(os.getenv("ADAPTIVE_MODEL_MAX_OUTPUT_TOKENS", "1400"))

# Current Standard short-context GPT-6 Astra rates. Kept configurable so the
# estimator can be updated without a code deploy if API pricing changes.
ADAPTIVE_PRICE_INPUT_USD_PER_M = float(os.getenv("ADAPTIVE_PRICE_INPUT_USD_PER_M", "10.0"))
ADAPTIVE_PRICE_CACHED_INPUT_USD_PER_M = float(os.getenv("ADAPTIVE_PRICE_CACHED_INPUT_USD_PER_M", "1.0"))
ADAPTIVE_PRICE_OUTPUT_USD_PER_M = float(os.getenv("ADAPTIVE_PRICE_OUTPUT_USD_PER_M", "50.0"))


# ===== ASTRA AUTO v1.1 diagnostics =====
ADAPTIVE_AUTO_STATS_LOG_MAX_MB = float(os.getenv("ADAPTIVE_AUTO_STATS_LOG_MAX_MB", "10"))
ADAPTIVE_AUTO_STATS_DEFAULT_HOURS = int(os.getenv("ADAPTIVE_AUTO_STATS_DEFAULT_HOURS", "24"))

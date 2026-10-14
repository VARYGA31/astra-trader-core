ASTRA SCALP + TELEGRAM MODE CONTROLLER

WHAT THIS ADDS
- One active strategy at a time: NORMAL or SCALP.
- NORMAL unchanged: 4H -> 1H -> 15M, including TRANSITION.
- SCALP v1: 1H regime -> 15M setup -> 5M confirmed trigger.
- Telegram commands /normal /scalp /pause /status /mode.
- Persistent Telegram keyboard: NORMAL | SCALP | PAUSE | STATUS.
- Switching NORMAL <-> SCALP is refused while an OKX position is open.
- PAUSE is always allowed: no new entries, but position monitor/SL/TP/emergency logic continue.
- Strategy mode persists under /data/strategy_mode.json across Redeploys.
- SCALP is BTC/ETH/GRAM only in v1. XAU remains NORMAL-only.
- Telegram open/partial/close notifications show ASTRA NORMAL or ASTRA SCALP.
- Analytics groups trades and decision funnel by strategy_mode.

SCALP SAFETY DEFAULTS
quality >= 70
confidence >= 82
5m trigger >= 4/5
spread <= 0.10%
5m ATR between 0.08% and 1.25%
TP1 >= 1.0R, TP2 >= 1.6R
leverage: 3x high-vol / 5x normal / 7x best setup
risk budget: 0.35% / 0.50% / 0.75%
stop distance: 0.08% .. 1.00%
3 scalp losses -> 1h scalp pause
scalp stop-loss cooldown per asset: 15m
FOK execution + post-fill R:R protection remains mandatory.

RAILWAY VARIABLES TO ADD
TELEGRAM_CONTROL_ENABLED=true
DEFAULT_STRATEGY_MODE=NORMAL
SCALP_ALLOWED_ASSETS=BTC,ETH,GRAM
SCALP_DECISION_INTERVAL_SECONDS=60
SCALP_MIN_QUALITY=70
SCALP_TRIGGER_MIN_COMPONENTS=4
SCALP_MIN_TRADE_CONFIDENCE=82
SCALP_NEWS_SETTLE_MINUTES=10
SCALP_MAX_SPREAD_PCT=0.10
SCALP_MIN_ATR_PCT=0.08
SCALP_MAX_ATR_PCT=1.25
SCALP_VOLUME_MIN_RATIO=0.75
SCALP_MIN_TP1_R=1.0
SCALP_MIN_TP2_R=1.6
SCALP_MIN_STOP_PCT=0.08
SCALP_MAX_STOP_PCT=1.00
SCALP_RISK_PCT_82_86=0.0035
SCALP_RISK_PCT_87_91=0.0050
SCALP_RISK_PCT_92_PLUS=0.0075
SCALP_HARD_RISK_PCT=0.0075
SCALP_LEVERAGE_HIGH_VOL=3
SCALP_LEVERAGE_NORMAL=5
SCALP_LEVERAGE_BEST_SETUP=7
SCALP_MAX_LEVERAGE=7
SCALP_STOP_LOSS_COOLDOWN_SECONDS=900
SCALP_LOSS_STREAK_LIMIT=3
SCALP_LOSS_STREAK_PAUSE_SECONDS=3600

KEEP
EXECUTION_MODE=okx_demo
AUTO_DECISION=true (only after tests)
EXECUTION_QUALITY_ENABLED=true
OKX_ENTRY_ORDER_TYPE=fok
EXCHANGE_SIDE_TP_SL=true
MOVE_SL_TO_BREAKEVEN_AFTER_TP1=true

SAFE INSTALL
1) Set AUTO_DECISION=false.
2) Upload all files from the patch ZIP, replacing same-name files.
3) Add the variables above.
4) Temporary Start Command:
   python repo_selfcheck.py && python test_scalp_mode.py && python test_telegram_mode_control.py && python worker.py
5) Redeploy. Expected BOTH tests status=OK and will_open_order=false, will_close_order=false, will_call_model=false.
6) /health should show status=ok, last_error=null, strategy_mode.mode=NORMAL.
7) Return Start Command: python worker.py
8) Set AUTO_DECISION=true and Redeploy.
9) In Telegram send /mode. Choose NORMAL or SCALP from the keyboard.

IMPORTANT
This is a Demo strategy experiment. A 5-minute strategy can trade more often but is more sensitive to fees, spread and noise. Do not raise leverage/risk before collecting clean SCALP statistics.

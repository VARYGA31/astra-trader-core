ASTRA MTF v2 — 4H REGIME / 1H SETUP / 15M TRIGGER

WHY
The previous bot had a good risk/execution layer but still made too many decisions from
a mostly 1H snapshot. This patch changes the decision architecture, not just thresholds.

NEW DECISION PIPELINE
4H regime
  -> 1H setup
    -> 15M confirmed trigger
      -> ASTRA final decision
        -> fresh MTF re-check
          -> Risk Engine
            -> OKX Demo

WHAT IS ADDED
- OKX confirmed 15m / 1H / 4H swap candles for BTC, ETH and GRAM.
- EMA20/50/200, RSI14, ATR14, structure, breakout, volume ratio on every timeframe.
- Deterministic MTF gate: ASTRA is not called unless 4H+1H+15M align.
- Fresh MTF re-check immediately before market order.
- Entry drift guard because the bot executes market orders.
- Loss-streak circuit breaker: 3 consecutive losses -> 6 hour pause by default.
- Confidence/MTF-quality risk tiers.
- Dynamic leverage: 2x high volatility, 3x normal, 5x only best setups.
- 15x is intentionally NOT enabled.
- Trade journal now records setup_type, MTF quality, trade quality, and risk tier.

SAFE RAILWAY SETTINGS FOR THE NEXT CLEAN DEMO TEST
AUTO_DECISION=false

Add/change:
DECISION_INTERVAL_SECONDS=900
MTF_ENABLED=true
MTF_MIN_QUALITY=72
MTF_TRIGGER_MIN_COMPONENTS=3
ENTRY_DRIFT_MAX_PCT=0.25
MIN_TRADE_CONFIDENCE=80

RISK_PCT_80_84=0.0035
RISK_PCT_85_91=0.005
RISK_PCT_92_PLUS=0.0075

DEFAULT_LEVERAGE=3
MAX_LEVERAGE=5
LEVERAGE_HIGH_VOL=2
LEVERAGE_NORMAL=3
LEVERAGE_BEST_SETUP=5
BEST_SETUP_MIN_QUALITY=90
BEST_SETUP_MIN_CONFIDENCE=92
BEST_SETUP_MAX_STOP_PCT=1.50

MIN_TP1_R=1.2
MIN_TP2_R=2.0

LOSS_STREAK_LIMIT=3
LOSS_STREAK_PAUSE_SECONDS=21600

For the clean validation phase I recommend:
MAX_OPEN_POSITIONS=1
MAX_TOTAL_EXPOSURE_PCT=0.20
MAX_POSITION_PCT=0.20
NORMAL_RISK_PCT=0.01
HARD_RISK_PCT=0.01

INSTALL
1) AUTO_DECISION=false
2) Replace/add all files in this patch.
3) Temporary Start Command:
   python repo_selfcheck.py && python test_mtf_strategy.py && python worker.py
4) The test is read-only: it DOES NOT open or close orders.
5) Expected: repo_selfcheck OK; test status OK; MTF data status OK for BTC/ETH/GRAM.
6) Return Start Command:
   python worker.py
7) Keep AUTO_DECISION=false and send the test log for review.
8) Only then enable AUTO_DECISION=true.

NOTE ON LEVERAGE
Leverage does not increase the allowed dollar risk. The Risk Engine still sizes from
the stop distance and the risk budget. 5x is only a margin-efficiency setting for the
best setups; it is not a reward for model confidence.

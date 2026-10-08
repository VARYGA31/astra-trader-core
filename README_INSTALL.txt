ASTRA ENTRY + EMERGENCY EXIT SAFETY PATCH

WHAT CHANGES
1) Anti-chase entry:
   - oversold SHORT entries near the 24h low / after an ATR-sized dump are blocked;
   - overbought LONG entries near the 24h high / after an ATR-sized pump are blocked;
   - extreme RSI no longer adds a trend-following gate point.

2) BTC/ETH correlation:
   - BTC and ETH cannot both be opened in the SAME direction at the same time.
   - GRAM remains independent.

3) Stop-loss re-entry:
   - after STOP_LOSS, that asset gets a 3600-second cooldown by default.

4) Emergency exit:
   - open positions are checked for a strong opposite market reversal every 30 sec;
   - score >= 4 needs 2 consecutive confirmations;
   - score >= 6 can close immediately;
   - a NEW fresh VERIFIED HIGH-impact news event is reviewed by ASTRA;
   - ASTRA can only return HOLD or CLOSE_NOW;
   - CLOSE_NOW requires confidence >= 80;
   - forced close is reduce-only market close;
   - normal exchange-side SL/TP remain the fallback if this mechanism fails.

SAFE INSTALL
A) Railway BEFORE upload:
   AUTO_DECISION=false
   EMERGENCY_EXIT_ENABLED=false

B) Replace:
   config.py
   decision_gate.py
   trade_cycle.py
   worker.py
   okx_demo_adapter.py
   okx_position_monitor.py
   repo_selfcheck.py
   telegram_notifier.py
   execution_router.py

C) Add:
   exit_news_decider.py
   position_exit_guard.py
   test_strategy_guards.py

D) Add Railway Variables:
   SHORT_CHASE_RSI=30
   LONG_CHASE_RSI=70
   CHASE_EXTREME_DISTANCE_PCT=0.60
   CHASE_IMPULSE_ATR_MULT=1.20
   BLOCK_BTC_ETH_SAME_DIRECTION=true
   STOP_LOSS_COOLDOWN_SECONDS=3600
   EMERGENCY_EXIT_COOLDOWN_SECONDS=3600
   EMERGENCY_EXIT_ENABLED=false
   EXIT_MARKET_CHECK_SECONDS=30
   EMERGENCY_MARKET_EXIT_SCORE=4
   EMERGENCY_MARKET_IMMEDIATE_SCORE=6
   EMERGENCY_MARKET_CONFIRMATIONS=2
   EMERGENCY_NEWS_MAX_AGE_MINUTES=30
   EMERGENCY_NEWS_MIN_CONFIDENCE=80

E) Temporary Start Command:
   python repo_selfcheck.py && python test_strategy_guards.py && python worker.py

The test does NOT open or close orders.
It may read current OKX Demo positions and live market data.

F) After test:
   return Start Command to:
   python worker.py

Then enable:
   EMERGENCY_EXIT_ENABLED=true

Keep AUTO_DECISION=false for ~10 minutes and inspect /health:
   last_exit_check
   last_news_exit_reviews
   emergency_exits
   exit_model_calls

If stable, set:
   AUTO_DECISION=true

IMPORTANT:
Existing positions are not automatically modified just by installing the patch.
When EMERGENCY_EXIT_ENABLED is switched on, existing tracked Demo positions can be closed
if the new opposite-market/news conditions are actually met.

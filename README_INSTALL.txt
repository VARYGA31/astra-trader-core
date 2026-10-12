ASTRA OBSERVABILITY + ANALYTICS PATCH

PURPOSE
This patch improves visibility and data collection WITHOUT changing the trading strategy.

IT DOES NOT CHANGE
- MTF thresholds
- LONG / SHORT logic
- Risk Engine
- leverage
- position sizing
- TP / SL / breakeven
- news verification rules
- emergency exit rules
- OKX execution

WHAT IT ADDS
1) Expanded /health:
   last_model_decision
   last_trade_rejection
   last_approved_trade
   skip_reasons
   observability
   performance

2) New /analytics endpoint:
   decision funnel
   model calls / skips / waits
   skip reasons
   deterministic rejection reasons
   performance by asset
   performance by LONG/SHORT
   performance by setup_type
   win rate
   profit factor
   average R where reconstructable
   max losing streak
   recent shadow setups

3) Persistent files under STATE_DIR (/data on Railway):
   /data/observability_state.json
   /data/decision_events.jsonl
   /data/shadow_setups.jsonl
   /data/news_events.jsonl

4) Shadow setup journal
   Promising blocked setups are recorded but NEVER traded.
   Default SHADOW_MIN_QUALITY=50.
   This lets us later test whether thresholds were too strict without weakening them now.

5) CLI report:
   python analytics_report.py
   python analytics_report.py --days 7

SAFE DEFAULT VARIABLES
OBSERVABILITY_ENABLED=true
SHADOW_JOURNAL_ENABLED=true
SHADOW_MIN_QUALITY=50
OBSERVABILITY_LOG_MAX_MB=20
ANALYTICS_RECENT_LIMIT=20

SAFE INSTALL
1) Set AUTO_DECISION=false.
2) Upload/replace all files from this ZIP.
3) Temporary Railway Start Command:
   python repo_selfcheck.py && python test_observability.py && python worker.py
4) Redeploy.
5) Expected:
   repo_selfcheck -> status OK
   test_observability -> status OK
   will_open_order -> false
   will_close_order -> false
   will_call_model -> false
6) Open /health and confirm status=ok, last_error=null.
7) Open /analytics. It may initially have zero decision rows; collection begins after deployment.
8) Return Start Command to:
   python worker.py
9) Set AUTO_DECISION=true.

NOTE
Existing trade_journal.jsonl is read for historical trade metrics, with duplicate close protection.
Decision-funnel statistics start from installation because older gate decisions were not persistently journaled.

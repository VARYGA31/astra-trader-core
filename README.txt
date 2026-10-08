ASTRA CLOSE-SPAM HOTFIX

IMMEDIATE:
1) Railway Variables:
   AUTO_DECISION=false
   TELEGRAM_ENABLED=false
2) Redeploy. This stops the Telegram flood while exchange-side TP/SL remains on OKX.

INSTALL:
Replace:
- okx_position_monitor.py
- telegram_notifier.py
Add:
- fix_close_spam_state.py

Temporary Start Command:
python fix_close_spam_state.py && python worker.py

Keep:
AUTO_DECISION=false
TELEGRAM_ENABLED=false

Expected cleanup status: OK.
The cleanup removes only stale local records for assets already closed on OKX.
It does not touch any open exchange position and does not alter demo ledger.

AFTER CLEANUP:
1) Return Start Command: python worker.py
2) Redeploy.
3) Set TELEGRAM_ENABLED=true
4) Keep AUTO_DECISION=false.
5) Open /health and send it for ledger verification before re-enabling autonomous trading.

The hotfix makes close processing idempotent:
- confirms position is absent 3 times;
- claims close event persistently;
- removes active record BEFORE Telegram/ledger side effects;
- suppresses duplicate close/partial Telegram events.

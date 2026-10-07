ASTRA TP/SL SAFETY PATCH

IMPORTANT BEFORE INSTALL:
1) Railway: AUTO_DECISION=false
2) Close all existing OKX Demo positions manually.
3) Confirm no open positions/orders from the old test.

Replace these files in GitHub:
- config.py
- risk_engine.py
- okx_demo_adapter.py
- okx_position_monitor.py
- execution_router.py
- trade_cycle.py
- repo_selfcheck.py
Add:
- test_protection_config.py

Railway variables to add:
MIN_TP1_R=1.0
MIN_TP2_R=1.8
ONE_POSITION_PER_ASSET=true
EXCHANGE_SIDE_TP_SL=true

Keep AUTO_DECISION=false for verification.

Temporary Start Command:
python repo_selfcheck.py && python test_protection_config.py && python worker.py

Expected:
repo_selfcheck status OK
test_protection_config status OK
will_open_order false
exchange_positions open_positions 0

Only after that perform ONE controlled OKX Demo trade test.
Do not enable AUTO_DECISION=true until the exchange shows TP/SL orders correctly.

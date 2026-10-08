ASTRA LEDGER REPAIR

Use because duplicate close notifications inflated the synthetic ledger.

1) Railway Variables:
   AUTO_DECISION=false
2) Keep worker/OKX running; existing exchange-side TP/SL remain on OKX.
3) Upload repair_demo_ledger.py and print_risk_config.py to repo root.
4) Temporary Start Command:
   python repair_demo_ledger.py && python print_risk_config.py && python worker.py
5) Redeploy.
6) Verify:
   ledger_after.initial_equity = 5000
   ledger_after.equity = 5000
   realized_pnl = 0
   closed_trades = 0
   and existing exchange positions are unchanged.
7) Return Start Command:
   python worker.py
8) Keep AUTO_DECISION=false until /health is reviewed.

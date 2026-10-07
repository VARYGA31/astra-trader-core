1) Railway: AUTO_DECISION=false
2) Close all OKX Demo positions.
3) Set INITIAL_EQUITY=5000
4) Upload reset_demo_ledger.py to repo root.
5) Temporary Start Command:
   python reset_demo_ledger.py && python worker.py
6) Redeploy and verify ledger_after.initial_equity = 5000.0
7) Return Start Command to: python worker.py
8) Then set AUTO_DECISION=true.

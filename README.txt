HOTFIX: trade_cycle.py was using mtf_gate and performance_guard without importing them.

1) Railway: AUTO_DECISION=false
2) Replace trade_cycle.py in the repository root with this file.
3) Temporary Start Command:
   python -c "import trade_cycle, mtf_gate, performance_guard; print('RUNTIME_IMPORTS_OK')" && python worker.py
4) Redeploy and verify RUNTIME_IMPORTS_OK.
5) Return Start Command to: python worker.py
6) Open /health. status should be ok and last_error should be null.
7) Only then set AUTO_DECISION=true.

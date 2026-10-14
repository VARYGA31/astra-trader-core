ASTRA FINAL DECISION CALIBRATION — CLEAN HOTFIX

WHY
Railway crashed with:
  SyntaxError: source code string cannot contain null bytes
while importing astra_client.

This clean hotfix contains ONLY text/source files.
There is NO __pycache__ directory and NO .pyc file in the ZIP.

INSTALL
1. Keep AUTO_DECISION=false.
2. Replace these files in the repository:
   astra_client.py
   observability.py
   repo_selfcheck.py
   test_final_decision_calibration.py
   test_no_null_bytes.py
3. Make sure any accidentally committed __pycache__ directory / *.pyc files are deleted.
4. Temporary Railway Start Command:
   python test_no_null_bytes.py && python repo_selfcheck.py && python test_final_decision_calibration.py && python worker.py
5. Redeploy.

Expected first test:
  status: OK
  null_byte_files: []
  syntax_errors: {}
  will_open_order: false
  will_close_order: false
  will_call_model: false

Do NOT enable AUTO_DECISION until the worker starts successfully and /health is status=ok.

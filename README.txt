ASTRA XAU Treasury hotfix

The first XAU preflight proved that XAU-USDT-SWAP is live and MTF data works.
The only broken part was the old Treasury XML URL.

This hotfix changes gold_macro.py to the official documented Treasury XML endpoint:
  /resource-center/data-chart-center/interest-rates/pages/xml

It requests the current month first and falls back to the current year.
It also parses Atom/OData namespaces robustly.

SAFE TEST
1) Keep AUTO_DECISION=false
2) Replace gold_macro.py
3) Temporary Start Command:
   python test_treasury_parser.py && python gold_macro.py && python test_xau_support.py && python worker.py
4) Redeploy
5) Expected:
   TREASURY_PARSER_OK
   treasury_yields.status = OK
   market.data_quality.status = OK
6) Keep AUTO_DECISION=false and send the log before enabling XAU.

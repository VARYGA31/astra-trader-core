ASTRA XAU / GOLD PATCH

WHAT THIS ADDS
- XAU becomes a fourth tradable asset: XAU-USDT-SWAP on OKX Demo.
- XAU uses the same 4H -> 1H -> 15M architecture, but with stricter thresholds.
- Official macro sources for gold:
  * Federal Reserve RSS
  * U.S. Bureau of Labor Statistics RSS
  * U.S. Bureau of Economic Analysis RSS
  * U.S. Treasury official daily yield-curve XML
- Reuters/Bloomberg/etc remain discovery/corroboration sources through Google News.
- MarketTwits remains discovery only; it cannot be the sole basis for a HIGH-impact trade.
- No DXY value is fabricated. DXY is explicitly UNAVAILABLE until a reliable feed is configured.
- Fresh verified HIGH-impact XAU macro news gets a short settle window before entry.
- Weekend XAU new entries are blocked by default.

XAU LEVERAGE
- high/elevated volatility: 5x
- normal qualified setup: 7x
- best setup only: 10x
- range is hard-capped to 5x..10x for XAU
- leverage DOES NOT increase the Risk Engine's dollar loss budget.

CRYPTO LEVERAGE IS UNCHANGED.

RAILWAY VARIABLES TO ADD
XAU_MTF_MIN_QUALITY=78
XAU_MIN_TRADE_CONFIDENCE=84
XAU_WEEKEND_BLOCK=true
XAU_MACRO_PRIMARY_REQUIRED=true
XAU_NEWS_SETTLE_MINUTES=5

XAU_MIN_LEVERAGE=5
XAU_NORMAL_LEVERAGE=7
XAU_MAX_LEVERAGE=10
XAU_BEST_SETUP_MIN_QUALITY=92
XAU_BEST_SETUP_MIN_CONFIDENCE=94
XAU_BEST_SETUP_MAX_STOP_PCT=1.50

SAFE INSTALL
1) Set AUTO_DECISION=false
2) Upload/replace all files from this patch.
3) Temporary Railway Start Command:
   python repo_selfcheck.py && python test_xau_support.py && python worker.py
4) Redeploy.
5) Expected:
   repo_selfcheck = OK
   test_xau_support.status = OK
   okx_instrument.instId = XAU-USDT-SWAP
   okx_instrument.state = live
   market.mtf_status = OK
   news.status = OK
   will_open_order = false
6) Return Start Command:
   python worker.py
7) Keep AUTO_DECISION=false and send the test log for review.
8) Only after review enable AUTO_DECISION=true.

IMPORTANT
Commodity availability and leverage limits can depend on the OKX account/region.
The read-only preflight verifies whether XAU-USDT-SWAP is actually available in your Demo account.
It does not set leverage and does not place any order.

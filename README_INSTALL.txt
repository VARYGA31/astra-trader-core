ASTRA EXECUTION QUALITY PATCH

WHY
The first post-MTF trade exposed a real execution-layer problem:
the strategy plan could have good R:R, but the actual OKX perpetual fill could
be materially worse than the planning/reference price.

THIS PATCH DOES NOT CHANGE
- NORMAL/TRANSITION signal rules
- MTF thresholds
- confidence thresholds
- risk tiers
- leverage rules
- news logic
- anti-chase
- TP/SL/breakeven behavior

WHAT CHANGES
1) ASTRA receives OKX perpetual last_price and is instructed to use it for entry.
2) Immediately before Risk Engine execution, trade_cycle reads the LIVE OKX swap ticker.
3) Risk Engine sizes from that tradable price instead of a spot price.
4) Before sending an order, execution_router rechecks R:R at the latest OKX price.
5) Entry becomes a price-bounded FOK limit:
   - full size fills inside our safe boundary, OR
   - zero trade.
   No unsafe market fallback.
6) The FOK limit is the stricter of:
   - allowed adverse slippage, and
   - the worst price that still preserves minimum TP1/TP2 R:R.
7) After fill, actual avgPx is audited again.
8) Journal / analytics now record planned entry, pre-order OKX reference,
   FOK limit, actual fill, slippage, planned R:R and actual R:R.

DEFAULT ENTRY CAPS
BTC/ETH: 0.15% max adverse slippage
GRAM:    0.20%
XAU:     0.10%

IMPORTANT
A canceled FOK is a GOOD outcome when price/liquidity is no longer acceptable.
The bot will report ENTRY_FOK_NOT_FILLED and wait for another setup.

RAILWAY VARIABLES
MIN_TP1_R=1.20
MIN_TP2_R=2.00
EXECUTION_QUALITY_ENABLED=true
OKX_ENTRY_ORDER_TYPE=fok
CRYPTO_MAX_ENTRY_SLIPPAGE_PCT=0.15
GRAM_MAX_ENTRY_SLIPPAGE_PCT=0.20
XAU_MAX_ENTRY_SLIPPAGE_PCT=0.10
POST_FILL_FAILSAFE_CLOSE=true

SAFE INSTALL
1) Set AUTO_DECISION=false.
2) Upload/replace all files in this ZIP.
3) Add the variables above (defaults are already safe if omitted).
4) Temporary Start Command:
   python repo_selfcheck.py && python test_execution_quality.py && python worker.py
5) Redeploy.
6) Expected:
   status: OK
   will_open_order: false
   will_close_order: false
   will_call_model: false
   bad_fill_rejected: true
   good_reference_passed: true
   limit_fill_passed: true
   worse_fill_rejected: true
7) Open /health and confirm status=ok, last_error=null.
8) Return Start Command:
   python worker.py
9) Re-enable AUTO_DECISION=true.

NOTE
This patch deliberately prefers "no fill" over a lower-quality fill.

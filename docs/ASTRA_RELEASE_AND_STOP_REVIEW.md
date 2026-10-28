# ASTRA release gates — capital protection first

## Research and promotion (no automatic trading)

A candidate entry strategy must NOT be enabled merely to increase the trade count.

1. Lock signal definitions and transaction-cost assumptions before examining the validation data. Never re-label the same validation segment as unseen after changes.
2. Require reproducible historical input validation (confirmed OKX swap candles, no forward leakage, no material missing data) and baseline NORMAL on the SAME market/time period.
3. For consideration, require **at least 30 completed simulated trades per asset in validation**, nonnegative average net R and PF >1 after modelled full roundtrip costs, plus robustness at an increased friction assumption (at least 0.24% vs 0.14% reference). Results across at least two uncorrelated asset groups are preferred; correlated symbols do not count as independent evidence.
4. Examine max drawdown in R, worst tail loss, time stability, turnover, fee sensitivity and open-position overlap. Verify signal source matches executable OKX demo instruments.
5. Then and only then, collect a forward chronological shadow sample with identical rules. Include simulated stops, funding, mark/last spread, maker/taker fees, FOK nonfills, and market data outage periods.
6. Only after independent positive evidence may a **new, separately gated** strategy be considered for demo entry. Risk Engine, daily loss, maximum drawdown, equity guard, exchange SL and emergency exits are not relaxed. Production activation always requires successful CI and postdeploy heartbeat.

A research test's negative result is useful evidence. It should NOT cause threshold-searching on the same validation segment.

## Read-only stop verification

ASTRA currently has attached exchange-side stop-loss algorithms and position polling. The new standalone `okx_stop_protection_audit.py` is **not wired into the production worker**. It may be exercised on an explicitly authorized OKX demo environment independently; do not claim it is monitoring live trading until such integration is independently approved and verified.

The auditor can read active positions and OKX `orders-algo-pending` for `conditional` and `oco` types. It never places, cancels or amends orders. Treat:

- `VERIFIED_ACTIVE_STOP` as evidence of an active matching stop *at observation time*, not a guaranteed exit price.
- `MISSING_STOP_ALGO` and `PARTIAL_STOP_COVERAGE` as urgent verification findings; verify against OKX trade/order-algo details and actual position side/contract size. Do not auto-close based solely on incomplete API lists.
- `UNKNOWN` as **not verified protected**. Partial API pagination, unknown stop order side, missing quantities or failed requests must never count as protected.
- `STOP_WORSE_THAN_PLAN` as an adverse stop drift needing investigation against the most recent planned stop; a tighter/trailing stop can legitimately differ.

## Repeated zero-trade days

Check the actual 24-hour decision funnel, then the active mode, model budget, MTF failure breakdown, news verification, and Risk Engine rejection counts. Zero new entries is **not** automatically an operational failure, and should not trigger a bypass of risk or MTF gates.

## Execution slippage forensic review

For adverse close prices (especially large GRAM-related historical anomalies), collect the original order id, attached algo ids, pending/historical algo status, trigger price type (mark/last/index), order fill timestamps and prices, fees/funding, and position side. A market stop trigger does not promise a fill at the trigger level. Attribute the cause only when primary exchange evidence exists; an observational journal alone is insufficient.

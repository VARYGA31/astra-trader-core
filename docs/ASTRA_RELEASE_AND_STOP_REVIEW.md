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


## Automatic evidence review (read-only)

- Run python research_promotion_contract.py --input regime_BTC.json --output promotion_BTC.json after historical research. The GitHub regime research workflow produces this artifact automatically.
- Contract: OKX confirmed candles, fixed 70/30 chronological split, preregistered rules, >=30 validation trades per asset/strategy, positive development and validation net R, validation PF >=1.10, positive stressed net R with PF >=1.10 at >=0.24% round-trip costs, and same-asset NORMAL baseline improvement.
- Even a pass means REQUIRES_NEW_FORWARD_SHADOW. Repeatedly examined historical OOS is not fresh blind testing. Never auto-promote, auto-trade, or blacklist assets.
- trade_incident_review.py analyzes deduplicated OKX demo closed trades: the setup, side, planned risk, realized PnL, approximate net R, costs, and exit relative to planned stop.
- CLOSE_REASON_INFERRED_FROM_PRICE is not verified historical order or trigger evidence. Causal attribution stays UNDETERMINED until algo history and exchange fills are checked.
- Railway heartbeats and Mission Control expose recent incident evidence and next verification steps. They do not control positions, leverage, risk or trade eligibility.

## Data fidelity limitations

- A partial TP or changed protection makes initial notional and initial stop geometry only indicative. Exact fill-level loss requires the historical algo and fill records.
- Exchange fees and funding can be signed negative amounts; do not subtract them from OKX realizedPnl again.
- Bad performance in a small sample does not justify removing an entire asset. Diagnose and test fixed hypotheses on unseen forward data.


## Explicit one-day OKX DEMO balance change acknowledgement (operator-only)

When a large *non-trade* demo balance movement trips the persistent daily stop, **do not** increase DAILY_LOSS_LIMIT_PCT or delete the ledger. After the operator acknowledges the movement and the account is confirmed flat, set `OKX_DEMO_BALANCE_CHANGE_ACK_DATE_UTC=YYYY-MM-DD` for the affected UTC day. This env setting has no effect on other days or non-demo trading.

The runtime verifies (1) signed OKX demo equity, (2) no open position across **all** returned OKX instruments, including untracked instruments, (3) OKX totalEq at least the bot's ledger equity, (4) today's realized trading PnL is still inside the unchanged daily limit, and (5) a negative account-balance change inconsistent with trading PnL. It then records the exact difference as a **user-acknowledged accounting adjustment**, explicitly *not* as a verified exchange transfer. Its evidence is retained in the daily equity baseline state.

The existing sticky daily-loss latch is cleared **at most once on that UTC date** only if the adjusted trading PnL is within the unchanged limit. Any later loss crosses the exact same daily limit and becomes sticky again; the acknowledgement cannot clear that second breach. Mark-to-market max drawdown, ledger equity, actual OKX totalEq, new stop losses, open position monitoring and order controls remain untouched. Never use this to waive genuine trading losses or assert that a withdrawal/deposit has been independently verified from OKX bills.

Remove the one-day env setting after expiry as operational housekeeping; the daily file remains in the persistent state volume and rolls over naturally at UTC midnight. Check `entry_halt_diagnostics` for original vs adjusted account change and operator acknowledgement before making any claim that entries are enabled.

# ASTRA TRADER — OKX Demo + Telegram

Current target exchange: **OKX Demo Trading**. Live trading is intentionally not implemented.

## Tradable runtime modes

ASTRA intentionally has only two trading strategies:

- **NORMAL** — ASTRA 4H → 1H → 15M across BTC/ETH/GRAM, XAU (when account-eligible), and a dynamic top-N liquid DeFi universe
- **MICRO v2** — 5M → 3M → 1M, OKX-native order flow, fee-aware NET-edge gate, hard 5-minute exit

`PAUSED` is a technical safety state: it blocks new entries while monitoring and exchange-side protection continue.

**SCALP and AUTO are retired as tradable runtime modes.** A persisted legacy SCALP/AUTO state is automatically migrated to NORMAL after deployment.

## Learning stays alive

Adaptive Trainer and Strategy Tournament remain available as a **shadow-only crypto lab**. They build/evaluate hypothetical candidates and empirical strategy evidence, but the lab:

- does not call ASTRA for trading decisions;
- has no order-routing capability;
- cannot switch the active trading mode;
- runs independently from NORMAL/MICRO execution.

Gold and DeFi Trainer screens remain shadow-only learning views. Separately, NORMAL can execute XAU and selected DeFi swaps through the same deterministic Risk/Execution pipeline.

## Safety and execution

- hard deterministic Python Risk Engine
- stop-based sizing; leverage does not increase the loss budget
- OKX Demo FOK entries
- exchange-side SL / TP protection
- post-fill execution-quality audit
- one-position / exposure / drawdown guards
- persistent state under `/data`
- Telegram mode control and diagnostics
- actual OKX `realizedPnl` is used for closed-trade NET performance

## Useful Telegram commands

- `/status`
- `/normal`
- `/micro`
- `/pause`
- `/micro_stats`
- `/shadow`
- `/trainer`
- `/tournament`

Safe defaults remain:

- `EXECUTION_MODE=paper`
- `AUTO_DECISION=false`
- live trading is not implemented


## Extended NORMAL markets

- Gold uses `XAU-USDT-SWAP` and must pass account-specific OKX instrument availability plus existing XAU macro/session guards.
- DeFi candidates are selected dynamically from `AAVE, UNI, LDO, PENDLE, CRV, MORPHO` using OKX liquidity/spread data.
- Only the top configured DeFi markets are active at once; default is 3.
- DeFi requires stricter confidence/quality, max 3x leverage, tighter slippage, protocol-security halts, and max one simultaneous DeFi position.
- MICRO remains limited to BTC/ETH/GRAM.


## Alpha Factory v1

ASTRA now includes a shadow-only empirical strategy factory. It mines cost-aware
Trainer outcomes for repeatable combinations of market features ("genes") and
evaluates each genome chronologically:

- train / out-of-sample split;
- walk-forward fold stability;
- NET expectancy in R after estimated friction;
- Profit Factor, max drawdown and recovery factor;
- lower-confidence-bound R;
- Spearman IC between setup quality and outcome;
- recent-vs-prior decay detection.

Factory statuses are `SHADOW_CHAMPION`, `PROMISING`, `CHALLENGER`,
`DEGRADED`, `REJECTED`, and `COLLECTING`.

**Alpha Factory has no model-call or order-routing capability.** Promotion is
research evidence only and cannot alter Risk Engine, leverage, execution, or
runtime mode.

## ASTRA Mission Control

A read-only futuristic dashboard is served at `/mission-control` and consumes
`/api/mission-control`. It shows:

- system / OKX Demo health;
- all-history NET PnL, PF, W/L and current mode;
- Alpha Factory genome constellation and OOS metrics;
- Strategy Tournament leaderboard;
- Trainer / MICRO / second-position shadow stats;
- active NORMAL universe and blocker diagnostics.

The UI exposes no trading actions. When `MISSION_CONTROL_ACCESS_TOKEN` is set,
all telemetry data endpoints require `Authorization: Bearer <token>`; the
public `/health` endpoint stays minimal for Railway health checks.


## Unified model cost control

All paid model-call paths share one daily budget and one global API circuit
breaker. NORMAL/MICRO final decisions default to `gpt-6.1-sol`; deterministic
Python gates still decide when a model opinion is worth requesting.

Defaults:

- hard daily paid-model call cap: 30;
- 3 calls reserved for emergency verified-news position review;
- hard estimated daily cost cap: USD 2.50;
- compact final-decision output cap: 900 tokens;
- `insufficient_quota` opens a global 30-minute circuit instead of hammering
  the API on every worker tick;
- generic rate limits/errors also back off globally;
- model usage, estimated spend, remaining budget and circuit state are visible
  in Mission Control.

The model layer remains advisory. Budget/circuit failures fail closed to WAIT
and never bypass Risk Engine or order-routing safeguards.


## Shadow Agent Council v1

ASTRA includes a zero-token multi-agent research layer inspired by ensemble
trading systems. It does **not** control live/demo execution in v1.

Six deterministic agents inspect the same already-fetched market package:

- **NOVA** — multi-timeframe trend / structure;
- **ORION** — momentum / timing;
- **VEGA** — order flow plus passive cross-asset scanner context;
- **ATLAS** — derivatives crowding from funding / OI availability;
- **CERBERUS** — anti-FOMO and hard safety veto;
- **HELIOS** — macro / verified-news context, especially for XAU.

The Council produces a shadow consensus score, agree/oppose counts and veto
status. Results are persisted with observability decisions for later OOS study.
There are no OpenAI calls, no order-routing imports, and no ability to mutate
risk, leverage, mode, or the live trade universe.

## VEGA cross-asset scanner

The scanner reuses market snapshots ASTRA already fetched and ranks fresh assets
by activity, volume expansion, spread quality, order-flow imbalance and relative
4h strength/weakness. It performs no extra network calls and does not change the
tradable universe. Mission Control visualizes both the scanner and the six-agent
Council as a shadow signal pipeline.

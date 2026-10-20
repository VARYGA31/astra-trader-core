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

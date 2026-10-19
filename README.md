# ASTRA TRADER — OKX Demo + Telegram

Current target exchange: **OKX Demo Trading**. Live trading is intentionally not implemented.

## Runtime modes

- **NORMAL** — 4H → 1H → 15M
- **SCALP** — 1H → 15M → 5M
- **MICRO v2** — 5M → 3M → 1M, OKX-native order flow, fee-aware NET-edge gate, hard 5-minute exit
- **AUTO** — Trainer + Strategy Tournament final selection
- **PAUSED** — blocks new entries; position protection remains active

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

## MICRO v2

MICRO uses OKX WebSocket `books5` + `trades` when fresh, with an OKX REST fallback. It reads the account trading fee when available and rejects geometry whose expected TP is consumed by estimated round-trip fee/slippage.

Useful Telegram commands:

- `/status`
- `/micro`
- `/micro_stats`
- `/scalp_stats`
- `/auto_stats`
- `/tournament`

Safe defaults remain:

- `EXECUTION_MODE=paper`
- `AUTO_DECISION=false`
- live trading is not implemented

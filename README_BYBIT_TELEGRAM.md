# ASTRA — Bybit Testnet + Telegram

## Execution modes
- `EXECUTION_MODE=paper` — current safe default.
- `EXECUTION_MODE=bybit_testnet` — sends orders only to Bybit Testnet through `pybit(testnet=True)`.

Never put API keys or Telegram tokens in GitHub.

## Telegram notifications
The bot sends:
- position opened
- TP1 partial close
- position closed
- PnL / leverage / asset / timeframe / notional / entry / exit / reason

Required environment variables:
- `TELEGRAM_ENABLED=true`
- `TELEGRAM_BOT_TOKEN=...`
- `TELEGRAM_CHAT_ID=...`

## Bybit Testnet
Required environment variables:
- `EXECUTION_MODE=bybit_testnet`
- `BYBIT_API_KEY=...`
- `BYBIT_API_SECRET=...`

The adapter:
- checks whether BTCUSDT / ETHUSDT / TONUSDT are actually available on Testnet
- rounds quantity to Bybit instrument rules
- uses market orders
- sets leverage
- installs an exchange-side hard Stop Loss using MarkPrice
- uses local worker logic for TP1 (50%) and TP2 (rest)
- monitors exchange positions and reports closure to Telegram

Current adapter assumes one-way mode (`BYBIT_POSITION_IDX=0`).

## First connection test
With credentials configured in the environment:

```bash
python test_bybit_telegram.py
```

This does NOT place a trade. It checks Telegram, Bybit wallet access, and the three configured instruments.

## Important
GRAM is an internal project label mapped to `TONUSDT`. The startup test verifies whether that instrument actually exists on Bybit Testnet. If unavailable, the bot blocks that asset instead of inventing a symbol.

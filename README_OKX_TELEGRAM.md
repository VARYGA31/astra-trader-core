# ASTRA — OKX Demo + Telegram

## Execution mode
Use:
- `EXECUTION_MODE=paper` for internal paper mode
- `EXECUTION_MODE=okx_demo` for OKX Demo Trading

## OKX Demo API
Create the API key inside OKX Demo Trading:
Trade -> Demo Trading -> Personal Center -> Demo Trading API.

Required Railway variables:
- OKX_API_KEY
- OKX_API_SECRET
- OKX_API_PASSPHRASE

The adapter adds `x-simulated-trading: 1` to authenticated requests.

## Instruments
ASTRA trades only:
- BTC -> BTC-USDT-SWAP
- ETH -> ETH-USDT-SWAP
- GRAM -> GRAM-USDT-SWAP

Availability and minimum contract sizes are checked at runtime.

## Risk
ASTRA still uses a synthetic $100 risk ledger even if the OKX demo account contains a larger demo balance.
The exchange balance is not used to increase risk.

## Stop loss
A hard stop is attached to the OKX order using an exchange-side attached stop-loss with Mark Price trigger.
This protects the position if Railway/OpenAI is temporarily unavailable.

## TP
- TP1: worker closes approximately 50%
- TP2: worker closes the remaining position
- full close / exchange-side SL is detected from OKX and reported to Telegram

## Telegram
Messages include:
- asset
- LONG/SHORT
- timeframe
- entry/exit
- position notional
- margin
- leverage
- SL/TP
- PnL
- close reason

## Safe connection test
Run:

python test_okx_telegram.py

It does not place an order. It checks:
- Telegram
- OKX Demo authentication
- account mode
- BTC/ETH/GRAM instruments
- whether a ~$20 position can satisfy minimum contract size

Keep `AUTO_DECISION=false` until the connection test and one manual demo trade have passed.

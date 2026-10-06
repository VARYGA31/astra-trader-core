# ASTRA TRADER — OKX Demo + Telegram

Current target exchange: OKX Demo Trading.

Core:
- BTC / ETH / GRAM only
- market + news context
- MarketTwits discovery feed
- news verification
- Astra decision engine
- hard Python risk engine
- paper mode and OKX Demo execution
- exchange-side hard stop loss
- partial TP1 / TP2 monitoring
- Telegram notifications
- persistent state under /data
- Railway worker

Safe defaults:
- EXECUTION_MODE=paper
- AUTO_DECISION=false
- live trading is not implemented

See README_OKX_TELEGRAM.md for setup.

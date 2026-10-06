# ASTRA TRADER — clean paper-trading repo

This repository is the clean pre-Railway version.

## What is included
- BTC / ETH / GRAM only
- Binance public spot market data with OKX fallback/context
- OKX swap funding/open interest
- Official + secondary RSS news
- MarketTwits Telegram public channel as fast discovery source
- High-impact verification/corroboration guard
- Decision context
- Risk engine
- Paper execution with partial TP1 and TP2
- Position monitor
- Cooldown
- Journal/statistics
- OpenAI Responses API client
- 24/7 worker (safe by default)
- Railway config
- Full preflight tests

## MarketTwits rule
`https://t.me/markettwits` is treated as `DISCOVERY_ONLY`.
It can trigger rapid analysis, but a HIGH-impact MarketTwits post cannot by itself authorize a trade.
It must be corroborated by an independent trusted/primary source.

## Clean GitHub install
You may delete the old repository files and upload the contents of this ZIP as the new root.

## One OpenAI Environment setup command
Copy the single line from `OPENAI_ENV_SETUP_COMMAND.txt` into one Setup Command.
Working directory: `/workspace`.

That one command:
1. cleans `/workspace`
2. downloads the whole GitHub repo
3. installs requirements
4. runs repository self-check

## Tests
After a new environment session:

```bash
cd /workspace
python preflight_all.py
python preflight_all.py --network
```

The first test is offline/synthetic.
The second also tests BTC/ETH/GRAM market/news/context and MarketTwits access.

## Safety
`AUTO_DECISION=false` by default.
Live exchange execution is intentionally disabled.
Do not add exchange API secrets until paper testing is complete.

## Railway later
Mount a persistent volume at `/data` and set `STATE_DIR=/data`.

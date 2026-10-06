ASSETS = {
    "BTC": {
        "binance_spot": "BTCUSDT",
        "okx_spot": "BTC-USDT",
        "okx_swap": "BTC-USDT-SWAP",
        "bybit_linear": "BTCUSDT",
        "aliases": ["bitcoin", "btc"],
    },
    "ETH": {
        "binance_spot": "ETHUSDT",
        "okx_spot": "ETH-USDT",
        "okx_swap": "ETH-USDT-SWAP",
        "bybit_linear": "ETHUSDT",
        "aliases": ["ethereum", "ether", "eth"],
    },
    # Internal project label GRAM. Exchange symbol availability is checked at runtime.
    "GRAM": {
        "binance_spot": "TONUSDT",
        "okx_spot": "TON-USDT",
        "okx_swap": "TON-USDT-SWAP",
        "bybit_linear": "TONUSDT",
        "aliases": ["gram", "ton", "toncoin", "the open network", "ton foundation", "telegram wallet"],
    },
}

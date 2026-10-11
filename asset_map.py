ASSETS = {
    "BTC": {
        "binance_spot": "BTCUSDT",
        "okx_spot": "BTC-USDT",
        "okx_swap": "BTC-USDT-SWAP",
        "aliases": ["bitcoin", "btc"],
    },
    "ETH": {
        "binance_spot": "ETHUSDT",
        "okx_spot": "ETH-USDT",
        "okx_swap": "ETH-USDT-SWAP",
        "aliases": ["ethereum", "ether", "eth"],
    },
    "GRAM": {
        "binance_spot": "GRAMUSDT",
        "okx_spot": "GRAM-USDT",
        "okx_swap": "GRAM-USDT-SWAP",
        "aliases": ["gram", "ton", "toncoin", "the open network", "ton foundation", "telegram wallet"],
    },
    "XAU": {
        # OKX renamed XAUT-USDT-SWAP to XAU-USDT-SWAP in Jan 2026.
        # XAU is a commodity perpetual, not a crypto spot asset.
        "binance_spot": None,
        "okx_spot": None,
        "okx_swap": "XAU-USDT-SWAP",
        "aliases": [
            "gold", "xau", "xauusd", "xauusdt", "bullion",
            "federal reserve", "fomc", "powell", "inflation", "cpi", "pce",
            "nonfarm payroll", "payrolls", "employment", "unemployment",
            "treasury yield", "treasury yields", "interest rate", "real yields"
        ],
    },
}

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
    "AAVE": {
        "binance_spot": None,
        "okx_spot": "AAVE-USDT",
        "okx_swap": "AAVE-USDT-SWAP",
        "aliases": ["aave", "aave protocol"],
        "lab_only": True,
        "market_group": "DEFI",
    },
    "UNI": {
        "binance_spot": None,
        "okx_spot": "UNI-USDT",
        "okx_swap": "UNI-USDT-SWAP",
        "aliases": ["uniswap", "uni"],
        "lab_only": True,
        "market_group": "DEFI",
    },
    "LDO": {
        "binance_spot": None,
        "okx_spot": "LDO-USDT",
        "okx_swap": "LDO-USDT-SWAP",
        "aliases": ["lido", "ldo", "lido dao"],
        "lab_only": True,
        "market_group": "DEFI",
    },
    "PENDLE": {
        "binance_spot": None,
        "okx_spot": "PENDLE-USDT",
        "okx_swap": "PENDLE-USDT-SWAP",
        "aliases": ["pendle", "pendle finance"],
        "lab_only": True,
        "market_group": "DEFI",
    },
    "CRV": {
        "binance_spot": None,
        "okx_spot": "CRV-USDT",
        "okx_swap": "CRV-USDT-SWAP",
        "aliases": ["curve", "curve finance", "crv"],
        "lab_only": True,
        "market_group": "DEFI",
    },
    "MORPHO": {
        "binance_spot": None,
        "okx_spot": "MORPHO-USDT",
        "okx_swap": "MORPHO-USDT-SWAP",
        "aliases": ["morpho", "morpho protocol"],
        "lab_only": True,
        "market_group": "DEFI",
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

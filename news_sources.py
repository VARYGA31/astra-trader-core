SOURCES = [
    {"id":"fed","name":"Federal Reserve","url":"https://www.federalreserve.gov/feeds/press_all.xml","tier":0,"kind":"PRIMARY","assets":["BTC","ETH","GRAM","XAU"],"category":"MACRO"},
    {"id":"bls_latest","name":"U.S. Bureau of Labor Statistics","url":"https://www.bls.gov/feed/bls_latest.rss","tier":0,"kind":"PRIMARY","assets":["XAU"],"category":"MACRO"},
    {"id":"bea","name":"U.S. Bureau of Economic Analysis","url":"https://apps.bea.gov/rss/rss.xml","tier":0,"kind":"PRIMARY","assets":["XAU"],"category":"MACRO"},
    {"id":"sec","name":"U.S. SEC","url":"https://www.sec.gov/news/pressreleases.rss","tier":0,"kind":"PRIMARY","assets":["BTC","ETH","GRAM"],"category":"REGULATION"},
    {"id":"ethereum_foundation","name":"Ethereum Foundation","url":"https://blog.ethereum.org/feed.xml","tier":0,"kind":"PRIMARY","assets":["ETH"],"category":"PROTOCOL"},
    {"id":"coinbase","name":"Coinbase Blog","url":"https://www.coinbase.com/blog/rss.xml","tier":1,"kind":"PRIMARY","assets":["BTC","ETH","GRAM"],"category":"EXCHANGE"},
    {"id":"coindesk","name":"CoinDesk","url":"https://www.coindesk.com/arc/outboundfeeds/rss/","tier":2,"kind":"SECONDARY","assets":["BTC","ETH","GRAM"],"category":"CRYPTO_MEDIA"},
    {"id":"decrypt","name":"Decrypt","url":"https://decrypt.co/feed","tier":2,"kind":"SECONDARY","assets":["BTC","ETH","GRAM"],"category":"CRYPTO_MEDIA"},
]

TRUSTED_DISCOVERY_PUBLISHERS = {
    "Reuters","Bloomberg","Associated Press","AP News","Financial Times","The Wall Street Journal",
    "WSJ","CNBC","BBC","CoinDesk","Decrypt"
}

DISCOVERY_QUERIES = {
    "BTC":["Bitcoin Reuters","Bitcoin ETF SEC","Bitcoin hack exchange","crypto Federal Reserve"],
    "ETH":["Ethereum Reuters","Ethereum SEC ETF","Ethereum exploit","Ethereum Foundation upgrade"],
    "GRAM":["TON The Open Network","TON Foundation Telegram","Toncoin Reuters","Telegram crypto TON"],
    "XAU":[
        "gold Reuters Federal Reserve",
        "gold Reuters CPI inflation",
        "gold Reuters nonfarm payrolls",
        "gold Reuters Treasury yields",
        "gold Reuters geopolitics",
        "XAU gold Bloomberg"
    ],
}

ALIASES = {
    "BTC":["bitcoin","btc"],
    "ETH":["ethereum","ether","eth"],
    "GRAM":["gram","ton","toncoin","the open network","ton foundation","telegram wallet"],
    "XAU":[
        "gold","xau","xauusd","xauusdt","bullion",
        "federal reserve","fomc","powell","inflation","cpi","pce",
        "nonfarm payroll","payrolls","employment","unemployment",
        "treasury yield","treasury yields","interest rate","real yields"
    ],
}

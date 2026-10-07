This patch fixes:
1) OKX Demo close exit-price/PnL reporting using close order details + fills.
2) OKX position-history latency handling for exchange-side SL/closures.
3) Astra confidence normalization: 0.99 -> 99.0 before Risk Engine.

Replace the four .py files in GitHub, then rerun the controlled roundtrip once.

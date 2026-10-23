#!/usr/bin/env python3
import unittest

import config
import market_snapshot
import trade_universe


class DemoMarketAlignmentTests(unittest.TestCase):
    def setUp(self):
        self.exec_mode=config.EXECUTION_MODE

    def tearDown(self):
        config.EXECUTION_MODE=self.exec_mode

    def test_okx_requests_use_simulated_header_in_demo(self):
        config.EXECUTION_MODE="okx_demo"
        h=market_snapshot._request_headers(market_snapshot.OKX+"/api/v5/market/ticker")
        self.assertEqual(h.get("x-simulated-trading"),"1")

    def test_non_okx_requests_do_not_get_simulated_header(self):
        config.EXECUTION_MODE="okx_demo"
        h=market_snapshot._request_headers(market_snapshot.BINANCE+"/api/v3/ticker/24hr")
        self.assertNotIn("x-simulated-trading",h)

    def test_demo_snapshot_uses_okx_swap_reference_not_binance(self):
        config.EXECUTION_MODE="okx_demo"
        original_ref=market_snapshot.okx_reference_market
        original_swap=market_snapshot.okx_swap
        original_mtf=market_snapshot.okx_multi_timeframe
        original_binance=market_snapshot.spot_binance
        try:
            market_snapshot.okx_reference_market=lambda inst:{
                "price":100.0,
                "ticker_24h":{},
                "changes_pct":{},
                "indicators":{},
                "regimes":{},
                "order_book":{},
                "trade_flow":{},
            }
            market_snapshot.okx_swap=lambda inst:{
                "last_price":100.0,"bid_price":99.9,"ask_price":100.1
            }
            market_snapshot.okx_multi_timeframe=lambda inst,include_micro=False:{
                "status":"OK","frames":{},"errors":[]
            }
            market_snapshot.spot_binance=lambda symbol:self.fail("Binance must not be used in okx_demo")
            out=market_snapshot.snapshot("BTC")
            self.assertEqual(out["spot_source"],"okx_demo_swap_reference")
            self.assertEqual(out["spot"]["price"],100.0)
            self.assertEqual(out["perp_okx"]["last_price"],100.0)
        finally:
            market_snapshot.okx_reference_market=original_ref
            market_snapshot.okx_swap=original_swap
            market_snapshot.okx_multi_timeframe=original_mtf
            market_snapshot.spot_binance=original_binance


class DemoTradableUniverseTests(unittest.TestCase):
    def setUp(self):
        self.exec_mode=config.EXECUTION_MODE
        self.gold=config.NORMAL_GOLD_TRADING_ENABLED
        self.defi=config.NORMAL_DEFI_TRADING_ENABLED
        self.topn=config.NORMAL_DEFI_TOP_N
        self.adapter=trade_universe.OKXDemoAdapter

    def tearDown(self):
        config.EXECUTION_MODE=self.exec_mode
        config.NORMAL_GOLD_TRADING_ENABLED=self.gold
        config.NORMAL_DEFI_TRADING_ENABLED=self.defi
        config.NORMAL_DEFI_TOP_N=self.topn
        trade_universe.OKXDemoAdapter=self.adapter

    def test_unavailable_demo_asset_does_not_consume_top_n_slot(self):
        config.EXECUTION_MODE="okx_demo"
        config.NORMAL_GOLD_TRADING_ENABLED=False
        config.NORMAL_DEFI_TRADING_ENABLED=True
        config.NORMAL_DEFI_TOP_N=2

        class Adapter:
            def account_tradability(self,asset):
                return {"available":asset!="UNI"}

        trade_universe.OKXDemoAdapter=Adapter
        u={"eligible":[
            {"asset":"UNI","spread_pct":0.01,"liquidity_score":100,"volume_proxy_usd":1000},
            {"asset":"AAVE","spread_pct":0.01,"liquidity_score":90,"volume_proxy_usd":900},
            {"asset":"CRV","spread_pct":0.01,"liquidity_score":80,"volume_proxy_usd":800},
        ]}
        assets=trade_universe.normal_assets(u)
        self.assertNotIn("UNI",assets)
        self.assertIn("AAVE",assets)
        self.assertIn("CRV",assets)


if __name__=="__main__":
    unittest.main()

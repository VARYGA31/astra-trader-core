#!/usr/bin/env python3
import unittest

import decision_gate
from okx_demo_adapter import OKXDemoAdapter


class OKXMarketFallbackTests(unittest.TestCase):
    def _adapter(self):
        adapter=object.__new__(OKXDemoAdapter)
        adapter.inst_id=lambda asset: f"{asset}-USDT-SWAP"
        return adapter

    def test_ticker_prefers_demo_public_market_data(self):
        adapter=self._adapter()
        adapter.public_get=lambda *a,**k: {"code":"0","data":[{"last":"7.25","bidPx":"7.24","askPx":"7.26"}]}
        adapter.market_get=lambda *a,**k: self.fail("fallback should not run")
        row=adapter.ticker_row("UNI")
        self.assertEqual(row["_astra_market_source"],"OKX_DEMO_PUBLIC")
        self.assertEqual(adapter.ticker("UNI"),7.25)

    def test_ticker_falls_back_to_public_market_data(self):
        adapter=self._adapter()
        adapter.public_get=lambda *a,**k: (_ for _ in ()).throw(RuntimeError("demo ticker unavailable"))
        adapter.market_get=lambda *a,**k: {"code":"0","data":[{"last":"7.31","bidPx":"7.30","askPx":"7.32"}]}
        price,source=adapter.ticker_with_source("UNI")
        self.assertEqual(price,7.31)
        self.assertEqual(source,"OKX_PUBLIC_FALLBACK")

    def test_ticker_reports_both_sources_when_unavailable(self):
        adapter=self._adapter()
        adapter.public_get=lambda *a,**k: (_ for _ in ()).throw(RuntimeError("demo down"))
        adapter.market_get=lambda *a,**k: (_ for _ in ()).throw(RuntimeError("public down"))
        with self.assertRaisesRegex(RuntimeError,"OKX_TICKER_UNAVAILABLE:UNI-USDT-SWAP"):
            adapter.ticker_row("UNI")


class DeFiAccountTradabilityGuardTests(unittest.TestCase):
    def setUp(self):
        self.original=decision_gate.OKXDemoAdapter

    def tearDown(self):
        decision_gate.OKXDemoAdapter=self.original

    def test_available_demo_instrument_passes(self):
        class Adapter:
            def account_tradability(self,asset):
                return {"available":True,"reason":"OK","instrument":"UNI-USDT-SWAP"}
        decision_gate.OKXDemoAdapter=Adapter
        package={"asset":"UNI","execution_mode":"okx_demo"}
        self.assertIsNone(decision_gate._defi_account_tradability_guard(package))

    def test_unavailable_demo_instrument_blocks_before_model(self):
        class Adapter:
            def account_tradability(self,asset):
                return {
                    "available":False,
                    "reason":"ACCOUNT_INSTRUMENT_UNAVAILABLE",
                    "instrument":"UNI-USDT-SWAP",
                }
        decision_gate.OKXDemoAdapter=Adapter
        package={"asset":"UNI","execution_mode":"okx_demo"}
        result=decision_gate._defi_account_tradability_guard(package)
        self.assertEqual(result["reason"],"DEFI_ACCOUNT_INSTRUMENT_UNAVAILABLE")
        self.assertFalse(result["call_model"])


if __name__=="__main__":
    unittest.main()

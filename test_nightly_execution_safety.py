#!/usr/bin/env python3
"""Offline regressions: GRAM exit-only and live OKX DeFi price limits."""
import unittest
from unittest.mock import patch

import config
import execution_router
import observability
import risk_engine
import trade_cycle
import trade_universe
from okx_demo_adapter import OKXDemoAdapter, OKXAPIError


class GRAMExitOnlyTests(unittest.TestCase):
    def test_all_entry_paths_reject_gram(self):
        self.assertIn("GRAM",config.ALLOWED_ASSETS)  # still map existing exits
        self.assertNotIn("GRAM",trade_universe.normal_assets({"status":"STALE"}))
        self.assertNotIn("GRAM",trade_universe.assets_for_mode("MICRO"))
        self.assertNotIn("GRAM",config.SCALP_ALLOWED_ASSETS)
        self.assertNotIn("GRAM",config.ADAPTIVE_ALLOWED_ASSETS)
        self.assertEqual(risk_engine.evaluate({"asset":"GRAM"})["reason"],"ASSET_NEW_ENTRIES_DISABLED")
        self.assertEqual(trade_cycle.execute({"asset":"GRAM","action":"LONG"})["reason"],"ASSET_NEW_ENTRIES_DISABLED")
        self.assertEqual(execution_router.open_trade({"asset":"GRAM","action":"LONG"},{})["reason"],"ASSET_NEW_ENTRIES_DISABLED")

    def test_railway_override_cannot_re_enable_gram(self):
        import importlib
        with patch.dict("os.environ",{"MICRO_ALLOWED_ASSETS":"BTC,GRAM", "SCALP_ALLOWED_ASSETS":"GRAM,ETH", "ADAPTIVE_ALLOWED_ASSETS":"GRAM,BTC"}):
            importlib.reload(config)
            try:
                self.assertNotIn("GRAM",config.MICRO_ALLOWED_ASSETS)
                self.assertNotIn("GRAM",config.SCALP_ALLOWED_ASSETS)
                self.assertNotIn("GRAM",config.ADAPTIVE_ALLOWED_ASSETS)
            finally:
                pass
        importlib.reload(config)


class PriceBandTests(unittest.TestCase):
    def setUp(self):
        self.adapter=object.__new__(OKXDemoAdapter)
        self.adapter.public_get=lambda path,params:{
            "data":[{"instId":"AAVE-USDT-SWAP","buyLmt":"134.5","sellLmt":"94.15"}]
        }

    def test_short_under_exchange_floor_fails_without_repricing(self):
        x=self.adapter.entry_price_limit_guard("AAVE","SHORT",93.95)
        self.assertFalse(x["passed"])
        self.assertEqual(x["limit_price"],93.95)
        self.assertEqual(x["exchange_bound"],94.15)
        self.assertTrue(self.adapter.entry_price_limit_guard("AAVE","SHORT",94.15)["passed"])

    def test_long_over_exchange_ceiling_fails(self):
        self.assertFalse(self.adapter.entry_price_limit_guard("AAVE","LONG",135)["passed"])
        self.assertTrue(self.adapter.entry_price_limit_guard("AAVE","LONG",134)["passed"])

    def test_missing_or_wrong_instrument_fails_closed(self):
        self.adapter.public_get=lambda path,params:{"data":[]}
        with self.assertRaises(OKXAPIError):
            self.adapter.entry_price_limit_guard("AAVE","SHORT",100)


class GuardDiagnosticsTests(unittest.TestCase):
    def test_xau_guard_flags_are_recorded_for_future_diagnosis(self):
        captured=[]
        package={"asset":"XAU","strategy_mode":"NORMAL","guards":{
            "market_ok":True,"news_ok":True,"critical_news_verified":True,
            "xau_session_ok":False,"gold_macro_ok":False,"gold_macro_primary_ok":True,
        }}
        with patch.object(observability,"_append_jsonl",side_effect=lambda p,row:captured.append(row)), \
             patch.object(observability,"_evaluate_mtf_shadow_outcomes"), \
             patch.object(observability.fok_shadow_analyzer,"record_rejection"):
            observability.record_decision(package,{"reason":"GUARD_BLOCK"},{"action":"WAIT"},{},False)
        self.assertEqual(captured[0]["guard_blockers"],["XAU_SESSION_OK_FALSE","GOLD_MACRO_OK_FALSE"])


if __name__=="__main__":
    unittest.main()

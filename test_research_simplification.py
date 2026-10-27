#!/usr/bin/env python3
"""Offline regression for a production-retired MICRO entry path.

No OKX credentials, orders, existing positions, or persistent state are used.
"""
import unittest
from unittest.mock import patch

import config
import strategy_mode
import trade_cycle
import risk_engine
import execution_router


class SimplifiedProductionModesTest(unittest.TestCase):
    def test_disabled_micro_cannot_be_entered_or_open_orders(self):
        with patch.object(config, "MICRO_NEW_ENTRIES_ENABLED", False):
            result = strategy_mode.switch_check("NORMAL", "MICRO", 0)
            self.assertFalse(result["allowed"])
            self.assertEqual(result["reason"], "MICRO_DISABLED")

            with self.assertRaisesRegex(ValueError, "MICRO_DISABLED"):
                strategy_mode.set_mode("MICRO", changed_by="REGRESSION")

            decision = {"asset": "BTC", "action": "LONG", "strategy_mode": "MICRO"}
            self.assertEqual(trade_cycle.execute(dict(decision))["reason"], "MICRO_DISABLED")
            self.assertEqual(risk_engine.evaluate(dict(decision))["reason"], "MICRO_DISABLED")
            self.assertEqual(execution_router.open_trade(dict(decision), {})["reason"], "MICRO_DISABLED")

            # Even an incorrectly labelled NORMAL decision with MICRO MTF is rejected.
            disguised = {"asset": "BTC", "action": "LONG",
                         "strategy_mode": "NORMAL", "mtf_mode": "MICRO"}
            self.assertEqual(risk_engine.evaluate(dict(disguised))["reason"], "MICRO_DISABLED")
            self.assertEqual(execution_router.open_trade(dict(disguised), {})["reason"], "MICRO_DISABLED")

    def test_normal_remains_available(self):
        with patch.object(config, "MICRO_NEW_ENTRIES_ENABLED", False):
            self.assertTrue(strategy_mode.switch_check("NORMAL", "NORMAL", 0)["allowed"])
            self.assertTrue(strategy_mode.switch_check("NORMAL", "PAUSED", 0)["allowed"])

    def test_feature_flag_preserves_existing_offline_micro_tests(self):
        with patch.object(config, "MICRO_NEW_ENTRIES_ENABLED", True):
            self.assertTrue(strategy_mode.switch_check("NORMAL", "MICRO", 0)["allowed"])


if __name__ == "__main__":
    unittest.main()

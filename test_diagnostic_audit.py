#!/usr/bin/env python3
"""Offline tests for read-only production diagnostics."""
import unittest
from unittest.mock import patch

import execution_audit
import trade_universe


class StopAuditTests(unittest.TestCase):
    def test_short_stop_overshoot(self):
        row={"asset":"GRAM","side":"SHORT","entry":1.235,"stop_loss":1.254,
             "exit_price":1.275,"reason":"EXCHANGE_CLOSE","pnl_usd":-49.46}
        audit=execution_audit.stop_exit_audit([row])
        self.assertEqual(audit["beyond_stop_count"],1)
        self.assertAlmostEqual(audit["beyond_stop"][0]["adverse_beyond_stop_r"],1.1053,places=4)
        self.assertFalse(audit["order_capability"])

    def test_good_exit_and_invalid_data_not_flagged(self):
        rows=[{"side":"LONG","entry":100,"stop_loss":95,"exit_price":96},
              {"side":"SHORT","entry":100,"stop_loss":105,"exit_price":99},
              {"side":"SHORT","entry":None,"stop_loss":105,"exit_price":110}]
        self.assertEqual(execution_audit.stop_exit_audit(rows)["beyond_stop_count"],0)

    def test_long_stop_overshoot(self):
        row={"asset":"ETH","side":"LONG","entry":100,"stop_loss":95,"exit_price":93}
        result=execution_audit.stop_exit_audit([row])["beyond_stop"][0]
        self.assertEqual(result["adverse_beyond_stop_r"],0.4)


class UniverseDiagnosticTests(unittest.TestCase):
    def test_passive_exclusions_do_not_affect_selected_assets(self):
        evidence={"status":"OK","generated_at_utc":"2026-10-25T00:00:00+00:00",
                  "eligible":[{"asset":"AAVE","instrument":"AAVE-USDT-SWAP","spread_pct":0.15},
                              {"asset":"CRV","instrument":"CRV-USDT-SWAP","spread_pct":0.04}],
                  "unavailable":[]}
        with patch.object(trade_universe,"normal_assets",return_value=("BTC","ETH","CRV")) as active:
            with patch.object(trade_universe.defi_universe,"cached_summary",return_value=evidence):
                result=trade_universe.summary()
        active.assert_called_once_with(None)
        self.assertEqual(result["defi_selection"]["assets"]["AAVE"]["reason"],"TRADE_SPREAD_TOO_WIDE")
        self.assertEqual(result["defi_selection"]["assets"]["CRV"]["reason"],"ACTIVE")


if __name__=="__main__":
    unittest.main()

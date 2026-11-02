#!/usr/bin/env python3
"""Offline mark-to-market safety regression; never contacts OKX."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import equity_guard


class EquityGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patcher=patch.object(equity_guard,"BASELINE",Path(self.tmp.name)/"baseline.json")
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        equity_guard._cached=None
        equity_guard._cached_until=0
        self.ledger={"equity":9886.0,"daily_pnl":-20.0}

    def test_unrealized_loss_reduces_equity_and_daily_pnl(self):
        first=equity_guard.snapshot(self.ledger,provider=lambda:{"data":[{"totalEq":"9800"}]})
        self.assertEqual(first["equity"],9800.0)
        self.assertEqual(first["daily_pnl"],-20.0)
        next_day=equity_guard.snapshot(self.ledger,provider=lambda:{"data":[{"totalEq":"9500"}]})
        self.assertEqual(next_day["equity"],9500.0)
        self.assertEqual(next_day["daily_pnl"],-300.0)

    def test_positive_exchange_equity_does_not_expand_risk_budget(self):
        result=equity_guard.snapshot(self.ledger,provider=lambda:{"data":[{"totalEq":"20000"}]})
        self.assertTrue(result["verified"])
        self.assertEqual(result["equity"],9886.0)

    def test_open_loss_cannot_hide_behind_extra_account_funds(self):
        result=equity_guard.snapshot(self.ledger,provider=lambda:{"data":[{"totalEq":"20000"}]},unrealized_pnl=-500.0)
        self.assertEqual(result["equity"],9386.0)
        self.assertEqual(result["daily_pnl"],-520.0)

    def test_unrelated_demo_total_equity_swing_above_ledger_cap_not_a_trade_loss(self):
        # An unrelated crypto/cash portfolio can change by >$1000 while
        # ASTRA has no realized loss and its admitted risk equity is unchanged.
        ledger={"equity":4808.85,"daily_pnl":0.0}
        first=equity_guard.snapshot(
            ledger,provider=lambda:{"data":[{"totalEq":"6008.29"}]})
        later=equity_guard.snapshot(
            ledger,provider=lambda:{"data":[{"totalEq":"5300.00"}]})
        self.assertTrue(later["verified"],later)
        self.assertLess(later["account_daily_change"],-700)
        self.assertEqual(later["daily_pnl"],0.0)
        self.assertEqual(later["conservative_risk_daily_change"],0.0)
        self.assertEqual(later["equity"],ledger["equity"])

    def test_total_eq_crossing_below_ledger_cap_is_a_real_drawdown(self):
        ledger={"equity":4808.85,"daily_pnl":0.0}
        equity_guard.snapshot(ledger,provider=lambda:{"data":[{"totalEq":"6008.29"}]})
        result=equity_guard.snapshot(
            ledger,provider=lambda:{"data":[{"totalEq":"4790.00"}]})
        self.assertAlmostEqual(result["daily_pnl"],-18.85,places=5)
        self.assertAlmostEqual(result["conservative_risk_daily_change"],-18.85,places=5)
        self.assertEqual(result["equity"],4790.0)

    def test_original_raw_baseline_migrates_without_erasing_realized_losses(self):
        ledger={"equity":4788.85,"daily_pnl":-20.0}
        from datetime import datetime,timezone
        today=datetime.now(timezone.utc).date().isoformat()
        equity_guard.BASELINE.write_text(
            __import__("json").dumps({
                "date_utc":today,"starting_total_eq":6008.29,
                "operator_demo_balance_ack":{"date_utc":"2020-01-01","offset_usd":-7}
            }),encoding="utf-8"
        )
        out=equity_guard.snapshot(
            ledger,provider=lambda:{"data":[{"totalEq":"5300"}]})
        self.assertEqual(out["daily_pnl"],-20.0,out)
        self.assertAlmostEqual(out["conservative_risk_daily_change"],-20,places=5)
        stored=__import__("json").loads(equity_guard.BASELINE.read_text())
        self.assertAlmostEqual(stored["starting_risk_equity"],4808.85,places=5)
        self.assertEqual(stored["starting_total_eq"],6008.29)
        self.assertIn("operator_demo_balance_ack",stored)

    def test_missing_position_upl_is_fail_closed(self):
        result=equity_guard.snapshot(self.ledger,provider=lambda:{"data":[{"totalEq":"9800"}]},unrealized_pnl=None)
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"],"OKX_POSITION_UPL_UNAVAILABLE")

    def test_missing_balance_is_fail_closed(self):
        result=equity_guard.snapshot(self.ledger,provider=lambda:{"data":[]})
        self.assertFalse(result["verified"])
        self.assertNotIn("equity",result)

    def test_bad_values_are_fail_closed(self):
        for value in ["nan","0","-1",None]:
            result=equity_guard.snapshot(self.ledger,provider=lambda:{"data":[{"totalEq":value}]})
            self.assertFalse(result["verified"])


if __name__=="__main__":
    unittest.main()

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

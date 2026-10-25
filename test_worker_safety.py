#!/usr/bin/env python3
"""Offline regressions for worker failure circuit and MICRO exit protection."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import config
import okx_position_monitor as monitor
import worker


class WorkerCircuitTests(unittest.TestCase):
    def test_three_consecutive_failures_pause_and_alert_once(self):
        original = worker.R.get("worker_exception_circuit")
        worker.R["worker_exception_circuit"] = {"active": False, "consecutive": 0, "threshold": 3}
        try:
            with patch.object(config, "WORKER_EXCEPTION_PAUSE_THRESHOLD", 3), \
                 patch.object(worker.strategy_mode, "set_mode") as set_mode, \
                 patch.object(worker.telegram_notifier, "notify_system") as notify:
                self.assertFalse(worker._trip_worker_circuit(2, "decision", "ValueError")["active"])
                self.assertTrue(worker._trip_worker_circuit(3, "decision", "ValueError")["active"])
                self.assertTrue(worker._trip_worker_circuit(4, "decision", "ValueError")["active"])
                self.assertEqual(set_mode.call_count, 1)
                self.assertEqual(notify.call_count, 1)
        finally:
            if original is None:
                worker.R.pop("worker_exception_circuit", None)
            else:
                worker.R["worker_exception_circuit"] = original


class MicroExitTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.record = {
            "asset": "BTC", "strategy_mode": "MICRO", "side": "LONG",
            "order_id": "entry-1", "qty_contracts": 1,
            "opened_at_utc": (datetime.now(timezone.utc) - timedelta(minutes=12)).isoformat(),
        }

    def _run(self, fail_close=False):
        calls = self.calls

        class Adapter:
            def exchange_active_summary(self):
                return {"assets": ["BTC"], "details": [], "open_positions": 1}

            def get_position(self, asset):
                return {"pos": "1"}

            def close_market(self, asset, side, qty):
                calls.append("close")
                if fail_close:
                    raise RuntimeError("CLOSE_UNAVAILABLE")
                return {"data": [{"ordId": "close-1"}]}

            def wait_filled(self, asset, order_id, timeout):
                calls.append("filled")
                return {"state": "filled"}

            def cancel_attached_algos(self, asset, order_id):
                calls.append("cleanup")
                return {"status": "OK"}

        with patch.object(config, "EXECUTION_MODE", "okx_demo"), \
             patch.object(monitor, "OKXDemoAdapter", Adapter), \
             patch.object(monitor, "load", return_value={"BTC": self.record}), \
             patch.object(monitor, "save"), \
             patch.object(monitor.trade_journal, "append_event"), \
             patch.object(monitor.demo_ledger, "status", return_value={}):
            return monitor.check_once()

    def test_close_fills_before_exchange_stop_cleanup(self):
        result = self._run()
        self.assertEqual(self.calls, ["close", "filled", "cleanup"])
        self.assertEqual(result["results"][0]["status"], "MICRO_TIME_STOP_FILLED")
        self.assertGreaterEqual(self.record["forced_close_details"]["overdue_seconds"], 0)

    def test_close_failure_preserves_exchange_stop(self):
        result = self._run(fail_close=True)
        self.assertEqual(self.calls, ["close"])
        self.assertEqual(result["results"][0]["status"], "MICRO_TIME_STOP_FAILED")


if __name__ == "__main__":
    unittest.main()

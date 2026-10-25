#!/usr/bin/env python3
import unittest

import normal_stop_shadow


class StopShadowTest(unittest.TestCase):
    def test_normal_stop_classifies_without_veto(self):
        record={"asset":"AAVE","strategy_mode":"NORMAL","entry":100,"stop_loss":99.9}
        result=normal_stop_shadow.examine(record)
        self.assertEqual(result["classification"],"BELOW_PROVISIONAL_MIN")
        self.assertFalse(result["order_capability"])
        self.assertFalse(result["risk_veto_capability"])

    def test_micro_has_no_audit(self):
        self.assertIsNone(normal_stop_shadow.examine({"strategy_mode":"MICRO","entry":100,"stop_loss":99}))


if __name__=="__main__":
    unittest.main()

#!/usr/bin/env python3
import json
import config
from okx_demo_adapter import OKXDemoAdapter

a = OKXDemoAdapter()
out = {
    "status": "OK",
    "will_open_order": False,
    "execution_mode": config.EXECUTION_MODE,
    "auto_decision": config.AUTO_DECISION,
    "exchange_side_tp_sl": config.EXCHANGE_SIDE_TP_SL,
    "move_sl_to_breakeven_after_tp1": config.MOVE_SL_TO_BREAKEVEN_AFTER_TP1,
    "open_positions": a.exchange_active_summary(),
    "note": (
        "Future split-TP orders will ask OKX to move the stop-loss trigger "
        "to the filled average entry price after TP1 triggers."
    ),
}
print(json.dumps(out, ensure_ascii=False, indent=2))

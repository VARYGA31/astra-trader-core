#!/usr/bin/env python3
import json
import config
from okx_demo_adapter import OKXDemoAdapter

out = {
    "status":"STARTED",
    "execution_mode":config.EXECUTION_MODE,
    "one_position_per_asset":config.ONE_POSITION_PER_ASSET,
    "exchange_side_tp_sl":config.EXCHANGE_SIDE_TP_SL,
    "min_tp1_r":config.MIN_TP1_R,
    "min_tp2_r":config.MIN_TP2_R,
    "will_open_order":False,
}

if config.EXECUTION_MODE != "okx_demo":
    out.update({"status":"FAILED","reason":"EXECUTION_MODE_NOT_okx_demo"})
else:
    a = OKXDemoAdapter()
    out["exchange_positions"] = a.exchange_active_summary()
    out["status"] = "OK"

print(json.dumps(out,ensure_ascii=False,indent=2))

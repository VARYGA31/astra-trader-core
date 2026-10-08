#!/usr/bin/env python3
import json
import config
from okx_demo_adapter import OKXDemoAdapter
import demo_ledger

names = [
    "INITIAL_EQUITY",
    "NORMAL_POSITION_PCT",
    "MAX_POSITION_PCT",
    "NORMAL_RISK_PCT",
    "HARD_RISK_PCT",
    "DAILY_LOSS_LIMIT_PCT",
    "MAX_DRAWDOWN_PCT",
    "MAX_TOTAL_EXPOSURE_PCT",
    "MAX_OPEN_POSITIONS",
    "DEFAULT_LEVERAGE",
    "MAX_LEVERAGE",
    "MIN_TP1_R",
    "MIN_TP2_R",
    "ONE_POSITION_PER_ASSET",
    "EXCHANGE_SIDE_TP_SL",
    "AUTO_DECISION",
    "EXECUTION_MODE",
]
cfg = {n: getattr(config, n, None) for n in names}
a = OKXDemoAdapter()
print(json.dumps({
    "status":"OK",
    "risk_config":cfg,
    "ledger":demo_ledger.status(),
    "exchange":a.exchange_active_summary(),
}, ensure_ascii=False, indent=2))

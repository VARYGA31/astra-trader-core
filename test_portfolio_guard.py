#!/usr/bin/env python3
import json
import config
import demo_ledger
from okx_demo_adapter import OKXDemoAdapter

a = OKXDemoAdapter()
summary = a.exchange_active_summary()
ledger = demo_ledger.status()
equity = float(ledger.get("equity") or config.INITIAL_EQUITY)
cap = equity * config.MAX_TOTAL_EXPOSURE_PCT

print(json.dumps({
    "status":"OK",
    "will_open_order":False,
    "will_close_order":False,
    "max_open_positions":config.MAX_OPEN_POSITIONS,
    "max_total_exposure_pct":config.MAX_TOTAL_EXPOSURE_PCT,
    "equity":equity,
    "exposure_cap_usd":cap,
    "exchange_summary":summary,
    "can_open_another_position_by_count":summary.get("open_positions",0) < config.MAX_OPEN_POSITIONS,
    "remaining_exposure_usd":max(0.0, cap-float(summary.get("current_exposure_usd",0))),
    "note":"Read-only portfolio guard test. No orders are sent."
}, ensure_ascii=False, indent=2))

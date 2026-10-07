#!/usr/bin/env python3
"""
Reset the synthetic OKX Demo risk ledger to INITIAL_EQUITY.

Safety:
- Refuses outside okx_demo mode.
- Refuses while AUTO_DECISION=true.
- Refuses if any OKX Demo positions are open.

This does NOT change the actual OKX Demo balance.
It only resets ASTRA's internal risk budget / realized PnL counters.
"""
import json

import config
import demo_ledger
from okx_demo_adapter import OKXDemoAdapter

result = {
    "status": "STARTED",
    "execution_mode": config.EXECUTION_MODE,
    "auto_decision": config.AUTO_DECISION,
    "target_initial_equity": config.INITIAL_EQUITY,
}

if config.EXECUTION_MODE != "okx_demo":
    result.update({"status":"REFUSED","reason":"EXECUTION_MODE_MUST_BE_okx_demo"})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(2)

if config.AUTO_DECISION:
    result.update({"status":"REFUSED","reason":"AUTO_DECISION_MUST_BE_false"})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(2)

adapter = OKXDemoAdapter()
summary = adapter.exchange_active_summary()
result["exchange_positions"] = summary

if summary.get("open_positions", 0) != 0:
    result.update({"status":"REFUSED","reason":"CLOSE_ALL_DEMO_POSITIONS_FIRST"})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(2)

state = demo_ledger.base()
demo_ledger.save(state)

result.update({
    "status":"OK",
    "ledger_after":demo_ledger.status(),
    "note":"Synthetic ASTRA demo risk ledger reset. Actual OKX Demo balance was not changed."
})
print(json.dumps(result, ensure_ascii=False, indent=2))

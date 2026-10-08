#!/usr/bin/env python3
"""
Repair ASTRA's synthetic Demo ledger after duplicate-close accounting corruption.

SAFE BEHAVIOR:
- OKX Demo only.
- AUTO_DECISION must be false.
- Does NOT close, resize, or modify any exchange position/order.
- Resets only /data/demo_ledger.json to INITIAL_EQUITY.
- Existing ETH/GRAM positions remain on OKX with their exchange-side TP/SL.
"""

import json
import config
import demo_ledger
from okx_demo_adapter import OKXDemoAdapter

out = {
    "status": "STARTED",
    "execution_mode": config.EXECUTION_MODE,
    "auto_decision": config.AUTO_DECISION,
    "target_initial_equity": config.INITIAL_EQUITY,
}

if config.EXECUTION_MODE != "okx_demo":
    out.update({"status":"REFUSED","reason":"EXECUTION_MODE_MUST_BE_okx_demo"})
    print(json.dumps(out, ensure_ascii=False, indent=2))
    raise SystemExit(2)

if config.AUTO_DECISION:
    out.update({"status":"REFUSED","reason":"SET_AUTO_DECISION_false_FIRST"})
    print(json.dumps(out, ensure_ascii=False, indent=2))
    raise SystemExit(2)

adapter = OKXDemoAdapter()
out["exchange_positions_before"] = adapter.exchange_active_summary()
out["ledger_before"] = demo_ledger.status()

# Reset only the synthetic accounting file.
fresh = demo_ledger.base()
demo_ledger.save(fresh)

out["ledger_after"] = demo_ledger.status()
out["exchange_positions_after"] = adapter.exchange_active_summary()
out["status"] = "OK"
out["note"] = (
    "Synthetic ledger reset only. Existing OKX Demo positions and exchange-side "
    "TP/SL were not changed."
)

print(json.dumps(out, ensure_ascii=False, indent=2))

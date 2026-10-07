#!/usr/bin/env python3
import json
import sys

import config
import trade_cycle
from astra_client import decide

asset = (sys.argv[1] if len(sys.argv) > 1 else "BTC").upper()

out = {
    "status": "STARTED",
    "asset": asset,
    "execution_mode": config.EXECUTION_MODE,
    "will_execute_trade": False,
}

if not config.OPENAI_API_KEY:
    out.update({"status":"FAILED","reason":"OPENAI_API_KEY_MISSING"})
    print(json.dumps(out, ensure_ascii=False, indent=2))
    raise SystemExit(1)

package = trade_cycle.prepare(asset, 12)
out["prepare_status"] = package.get("status")
out["guards"] = package.get("guards", {})

if package.get("status") != "READY_FOR_ASTRA":
    out.update({"status":"FAILED","reason":"CONTEXT_NOT_READY"})
    print(json.dumps(out, ensure_ascii=False, indent=2))
    raise SystemExit(1)

decision = decide(package)

out.update({
    "status":"OK",
    "model": config.OPENAI_MODEL if not config.OPENAI_PROMPT_ID else "PROMPT_ID",
    "decision": decision,
    "will_execute_trade": False,
})
print(json.dumps(out, ensure_ascii=False, indent=2))

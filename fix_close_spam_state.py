#!/usr/bin/env python3
"""
One-time close-spam cleanup.

- Requires OKX Demo.
- Requires AUTO_DECISION=false.
- Removes local active-trade records ONLY for assets that are already closed on OKX.
- Marks those stale records as processed so they cannot be announced/accounted again.
- Does NOT change open OKX positions.
- Does NOT change the demo ledger; inspect /health afterwards and repair ledger separately if needed.
"""
import json
from pathlib import Path
from datetime import datetime, timezone

import config
from okx_demo_adapter import OKXDemoAdapter

STATE = Path(config.STATE_DIR) / "okx_active_trades.json"
PROCESSED = Path(config.STATE_DIR) / "okx_processed_closes.json"

def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

out = {
    "status":"STARTED",
    "execution_mode":config.EXECUTION_MODE,
    "auto_decision":config.AUTO_DECISION,
}

if config.EXECUTION_MODE != "okx_demo":
    out.update({"status":"REFUSED","reason":"EXECUTION_MODE_MUST_BE_okx_demo"})
    print(json.dumps(out, ensure_ascii=False, indent=2))
    raise SystemExit(2)

if config.AUTO_DECISION:
    out.update({"status":"REFUSED","reason":"AUTO_DECISION_MUST_BE_false"})
    print(json.dumps(out, ensure_ascii=False, indent=2))
    raise SystemExit(2)

adapter = OKXDemoAdapter()
exchange = adapter.exchange_active_summary()
open_assets = set(exchange.get("assets", []))

state = load(STATE)
processed = load(PROCESSED)
removed = []
kept = []

for asset, rec in list(state.items()):
    if asset in open_assets:
        kept.append(asset)
        continue

    key = f"{asset}:{rec.get('order_id') or rec.get('opened_at_utc') or 'unknown'}"
    processed[key] = {
        "asset":asset,
        "order_id":rec.get("order_id"),
        "status":"CLEANED_STALE_CLOSE",
        "processed_at_utc":datetime.now(timezone.utc).isoformat(),
    }
    state.pop(asset, None)
    removed.append({"asset":asset,"close_key":key})

save(STATE, state)
save(PROCESSED, processed)

out.update({
    "status":"OK",
    "exchange_positions":exchange,
    "removed_stale_closed_records":removed,
    "kept_open_records":kept,
    "note":"Demo ledger was NOT modified. Check /health after restart."
})
print(json.dumps(out, ensure_ascii=False, indent=2))

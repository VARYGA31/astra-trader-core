#!/usr/bin/env python3
"""Pure persistent SCALP stats test. No network or orders."""
import json,tempfile
from pathlib import Path
import scalp_stats
old=scalp_stats.FILE
try:
    with tempfile.TemporaryDirectory() as td:
        scalp_stats.FILE=Path(td)/"scalp_stats.jsonl"
        p={"asset":"BTC"}
        scalp_stats.record(p,{"call_model":False,"reason":"SCALP_5M_TRIGGER_BLOCK","mtf":{"primary_blocker":"SCALP_5M_TRIGGER_BLOCK"}}, {"action":"WAIT"},{"status":"NO_TRADE","reason":"SCALP_5M_TRIGGER_BLOCK"},False)
        scalp_stats.record(p,{"call_model":True,"reason":"MODEL_GATE_PASS","scalp_tier":"FAST","mtf":{"tier":"FAST"}}, {"action":"WAIT","confidence":88,"wait_category":"STRUCTURE_CONFLICT","scalp_tier":"FAST"},{"status":"NO_TRADE","reason":"ASTRA_WAIT"},True)
        scalp_stats.record(p,{"call_model":True,"reason":"MODEL_GATE_PASS","scalp_tier":"PRIME","mtf":{"tier":"PRIME"}}, {"action":"LONG","confidence":92,"scalp_tier":"PRIME"},{"status":"OKX_DEMO_OPENED"},True)
        s=scalp_stats.summary(6)
        assert s["checks"]==3,s
        assert s["blockers"].get("5M_TRIGGER")==1,s
        assert s["gate_passes_by_tier"].get("FAST")==1,s
        assert s["gate_passes_by_tier"].get("PRIME")==1,s
        assert s["model_waits"]==1,s
        assert s["opened_trades"]==1,s
finally:
    scalp_stats.FILE=old
print(json.dumps({"status":"OK","will_open_order":False,"will_close_order":False,"will_call_model":False,"stats_test":"OK"},ensure_ascii=False,indent=2))

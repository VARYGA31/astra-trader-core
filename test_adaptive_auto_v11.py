#!/usr/bin/env python3
"""Pure AUTO v1.1 regression. No network, OpenAI or orders."""
import json,tempfile
from pathlib import Path
from datetime import datetime,timezone

import config
import adaptive_client
import adaptive_cost
import adaptive_stats

req=adaptive_client._execution_requirements()
assert req["NORMAL"]["min_confidence"]==float(config.MIN_TRADE_CONFIDENCE),req
assert req["NORMAL"]["min_setup_quality"]==float(max(config.MTF_MIN_QUALITY,config.MIN_TRADE_CONFIDENCE)),req
assert req["SCALP_FAST"]["min_confidence"]==float(config.SCALP_FAST_MIN_TRADE_CONFIDENCE),req
assert req["SCALP_FAST"]["min_tp2_r"]==float(config.SCALP_FAST_MIN_TP2_R),req
assert req["SCALP_PRIME"]["min_confidence"]==float(config.SCALP_MIN_TRADE_CONFIDENCE),req

old_usage=adaptive_cost.USAGE_FILE
old_log=adaptive_stats.LOG
try:
    with tempfile.TemporaryDirectory() as td:
        td=Path(td)
        adaptive_cost.USAGE_FILE=td/"usage.jsonl"
        adaptive_stats.LOG=td/"auto.jsonl"

        # Fill enough calls/cost that baseline reserve must be protected,
        # while the hard daily cap still has room.
        now=datetime.now(timezone.utc).isoformat()
        with adaptive_cost.USAGE_FILE.open("w",encoding="utf-8") as f:
            for _ in range(max(1,int(config.ADAPTIVE_MAX_MODEL_CALLS_PER_DAY)-int(config.ADAPTIVE_BASELINE_RESERVE_CALLS))):
                f.write(json.dumps({
                    "timestamp_utc":now,
                    "strategy_mode":"AUTO",
                    "model":"test",
                    "input_tokens":1000,
                    "cached_input_tokens":0,
                    "output_tokens":100,
                    "total_tokens":1100,
                })+"\n")
        reserve=adaptive_cost.reserve_status()
        assert reserve["baseline_allowed"] is False,reserve

        adaptive_stats.record({
            "status":"SKIPPED",
            "reason":"BASELINE_RESERVE_PROTECTED",
            "cost_plan":{"reason":"BASELINE_RESERVE_PROTECTED","local_scan":{"triggered":False,"best":{}}},
        })
        adaptive_stats.record({
            "status":"OK",
            "reason":"ADAPTIVE_CYCLE",
            "decision":{"asset":"BTC","action":"LONG","strategy_mode":"SCALP","confidence":91,"adaptive_setup_quality":78,"scalp_tier":"FAST"},
            "result":{"best_opportunity":{"asset":"BTC","action":"LONG","strategy":"SCALP","confidence":91,"setup_quality":78,"scalp_tier":"FAST"}},
            "execution":{"status":"REJECTED","reason":"TP2_REWARD_RISK_TOO_LOW"},
            "cost_plan":{"reason":"LOCAL_OPPORTUNITY_TRIGGER","local_scan":{"triggered":True,"best":{"asset":"BTC","direction":"LONG","score":5.1}}},
        })
        s=adaptive_stats.summary(24)
        assert s["cycles"]==2,s
        assert s["model_calls"]==1,s
        assert s["trade_proposals"]==1,s
        assert s["execution_rejections"].get("TP2_REWARD_RISK_TOO_LOW")==1,s
        assert s["cost_skips"].get("BASELINE_RESERVE_PROTECTED")==1,s
finally:
    adaptive_cost.USAGE_FILE=old_usage
    adaptive_stats.LOG=old_log

print(json.dumps({
    "status":"OK",
    "will_open_order":False,
    "will_close_order":False,
    "will_call_model":False,
    "risk_alignment":"OK",
    "budget_reserve":"OK",
    "auto_stats":"OK",
},ensure_ascii=False,indent=2))

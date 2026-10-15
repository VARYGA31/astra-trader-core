#!/usr/bin/env python3
"""Pure Cost-Smart planner test. No network, OpenAI or orders."""
import json,tempfile
from pathlib import Path
from datetime import datetime,timezone,timedelta

import config
import adaptive_cost

def tf(trend,structure,momentum,change=.25,vol=1.6,breakout=False):
    return {
        "regimes":{"trend":trend,"structure":structure,"momentum":momentum},
        "changes_pct":{"1bar":change},
        "structure":{"breakout_up":breakout,"breakout_down":False},
        "volume":{"ratio_to_avg20":vol},
    }

def package():
    return {
        "guards":{
            "market_stale":False,"market_ok":True,"news_ok":True,
            "critical_news_verified":True,
        },
        "decision_context":{"market":{
            "multi_timeframe":{"frames":{
                "1h":tf("BULLISH","BULLISH","BULLISH"),
                "15m":tf("BULLISH","BULLISH","BULLISH"),
                "5m":tf("BULLISH","BULLISH","BULLISH",breakout=True),
            }},
            "perp_okx":{"bid_price":100.0,"ask_price":100.02},
        }},
    }

scan=adaptive_cost.local_scan({"BTC":package()})
assert scan["triggered"] is True,scan

old=adaptive_cost.USAGE_FILE
try:
    with tempfile.TemporaryDirectory() as td:
        adaptive_cost.USAGE_FILE=Path(td)/"usage.jsonl"
        b=adaptive_cost.budget_status()
        assert b["allowed"] is True,b

        recent=(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat()
        p=adaptive_cost.plan({"BTC":package()},{"last_model_call_at_utc":recent},force=False)
        assert p["call_model"] is False,p
        assert p["reason"]=="COST_SMART_WAIT",p

        old_enough=(datetime.now(timezone.utc)-timedelta(minutes=config.ADAPTIVE_BASE_MODEL_INTERVAL_MINUTES+1)).isoformat()
        p2=adaptive_cost.plan({"BTC":package()},{"last_model_call_at_utc":old_enough},force=False)
        assert p2["call_model"] is True,p2
        assert p2["reason"]=="BASELINE_INTERVAL",p2
finally:
    adaptive_cost.USAGE_FILE=old

print(json.dumps({
    "status":"OK",
    "will_open_order":False,
    "will_close_order":False,
    "will_call_model":False,
    "local_trigger":"OK",
    "budget_guard":"OK",
    "baseline_interval_minutes":config.ADAPTIVE_BASE_MODEL_INTERVAL_MINUTES,
    "max_calls_per_day":config.ADAPTIVE_MAX_MODEL_CALLS_PER_DAY,
    "daily_estimated_cost_cap_usd":config.ADAPTIVE_MAX_ESTIMATED_USD_PER_DAY,
},ensure_ascii=False,indent=2))

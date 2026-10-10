#!/usr/bin/env python3
import json
import config
import decision_context
import mtf_gate
import performance_guard

out={
    "status":"OK",
    "will_open_order":False,
    "will_close_order":False,
    "config":{
        "mtf_enabled":config.MTF_ENABLED,
        "mtf_min_quality":config.MTF_MIN_QUALITY,
        "entry_drift_max_pct":config.ENTRY_DRIFT_MAX_PCT,
        "min_trade_confidence":config.MIN_TRADE_CONFIDENCE,
        "risk_tiers":[config.RISK_PCT_80_84,config.RISK_PCT_85_91,config.RISK_PCT_92_PLUS],
        "max_leverage":config.MAX_LEVERAGE,
        "loss_streak_limit":config.LOSS_STREAK_LIMIT,
        "loss_streak_pause_seconds":config.LOSS_STREAK_PAUSE_SECONDS,
    },
    "performance_guard":performance_guard.status(),
    "assets":{},
}

for asset in config.ALLOWED_ASSETS:
    p={
        "asset":asset,
        "decision_context":decision_context.build(asset,2),
    }
    out["assets"][asset]={
        "market_status":p["decision_context"].get("market",{}).get("status"),
        "mtf_status":p["decision_context"].get("market",{}).get("multi_timeframe",{}).get("status"),
        "gate":mtf_gate.evaluate(p),
    }

print(json.dumps(out,ensure_ascii=False,indent=2))

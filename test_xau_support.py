#!/usr/bin/env python3
"""
READ-ONLY XAU preflight. It does not set leverage and does not place/close orders.
"""
import json
import config
import market_snapshot
import news_snapshot
import decision_context
import mtf_gate
from okx_demo_adapter import OKXDemoAdapter

out={
    "status":"STARTED",
    "will_open_order":False,
    "will_close_order":False,
    "will_set_leverage":False,
    "xau_config":{
        "allowed":"XAU" in config.ALLOWED_ASSETS,
        "mtf_min_quality":config.XAU_MTF_MIN_QUALITY,
        "min_trade_confidence":config.XAU_MIN_TRADE_CONFIDENCE,
        "leverage_min":config.XAU_MIN_LEVERAGE,
        "leverage_normal":config.XAU_NORMAL_LEVERAGE,
        "leverage_max":config.XAU_MAX_LEVERAGE,
        "weekend_block":config.XAU_WEEKEND_BLOCK,
        "news_settle_minutes":config.XAU_NEWS_SETTLE_MINUTES,
    },
}

try:
    a=OKXDemoAdapter()
    info=a.instrument("XAU")
    out["okx_instrument"]={
        "status":"OK",
        "instId":info.get("instId"),
        "state":info.get("state"),
        "ctVal":info.get("ctVal"),
        "ctValCcy":info.get("ctValCcy"),
        "lotSz":info.get("lotSz"),
        "minSz":info.get("minSz"),
        "tickSz":info.get("tickSz"),
    }
    out["ticker"]=a.ticker("XAU")
except Exception as e:
    out["okx_instrument"]={"status":"FAILED","error":str(e)}

try:
    m=market_snapshot.snapshot("XAU")
    out["market"]={
        "status":m.get("status"),
        "data_quality":m.get("data_quality"),
        "spot_source":m.get("spot_source"),
        "price":m.get("spot",{}).get("price"),
        "mtf_status":m.get("multi_timeframe",{}).get("status"),
        "gold_macro":m.get("gold_macro"),
    }
except Exception as e:
    out["market"]={"status":"FAILED","error":str(e)}

try:
    n=news_snapshot.snapshot("XAU",2)
    out["news"]={
        "status":n.get("status"),
        "summary":n.get("summary"),
        "guard":n.get("guard"),
        "latest":[
            {k:e.get(k) for k in ("source","published_at_utc","title","event_type","impact_hint","trade_usable")}
            for e in n.get("events",[])[:5]
        ],
    }
except Exception as e:
    out["news"]={"status":"FAILED","error":str(e)}

try:
    c=decision_context.build("XAU",2)
    out["guards"]=c.get("guards")
    out["mtf_gate"]=mtf_gate.evaluate({
        "asset":"XAU",
        "decision_context":c,
    })
except Exception as e:
    out["decision_context"]={"status":"FAILED","error":str(e)}

checks=[
    out.get("okx_instrument",{}).get("status")=="OK",
    out.get("market",{}).get("status")=="OK",
    out.get("news",{}).get("status")=="OK",
]
out["status"]="OK" if all(checks) else "FAILED"
print(json.dumps(out,ensure_ascii=False,indent=2))

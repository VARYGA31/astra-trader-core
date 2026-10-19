#!/usr/bin/env python3
import sys,json
from datetime import datetime,timezone
import config,market_snapshot,news_snapshot

def build(asset,hours=12,include_micro=False):
    if asset not in config.ALLOWED_ASSETS:
        return {"status":"TRADE_NOT_ALLOWED"}

    m=market_snapshot.snapshot(asset,include_micro=include_micro)
    n=news_snapshot.snapshot(asset,hours)

    guards={
        "market_ok":m.get("data_quality",{}).get("status")!="FAILED",
        "news_ok":n.get("summary",{}).get("data_quality")!="FAILED",
        "critical_news_verified":n.get("guard",{}).get("critical_news_verified",False),
    }

    if asset=="XAU":
        utc=datetime.now(timezone.utc)
        guards["xau_session_ok"] = (not config.XAU_WEEKEND_BLOCK) or utc.weekday()<5
        gm=m.get("gold_macro") or {}
        guards["gold_macro_ok"] = gm.get("status") in {"OK","PARTIAL"} and (
            (gm.get("treasury_yields") or {}).get("status")=="OK"
        )
        guards["gold_macro_primary_ok"] = (
            n.get("guard",{}).get("macro_primary_ok",False)
            if config.XAU_MACRO_PRIMARY_REQUIRED else True
        )

    return {
        "status":"OK",
        "asset":asset,
        "generated_at_utc":datetime.now(timezone.utc).isoformat(),
        "market":m,
        "news":n,
        "guards":guards,
    }

if __name__=="__main__":
    a=(sys.argv[1] if len(sys.argv)>1 else "BTC").upper()
    h=int(sys.argv[2]) if len(sys.argv)>2 else 12
    print(json.dumps(build(a,h),ensure_ascii=False,separators=(",",":")))

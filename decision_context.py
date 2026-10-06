#!/usr/bin/env python3
import sys,json
from datetime import datetime,timezone
import config,market_snapshot,news_snapshot
def build(asset,hours=12):
    if asset not in config.ALLOWED_ASSETS:return {"status":"TRADE_NOT_ALLOWED"}
    m=market_snapshot.snapshot(asset);n=news_snapshot.snapshot(asset,hours)
    return {"status":"OK","asset":asset,"generated_at_utc":datetime.now(timezone.utc).isoformat(),
            "market":m,"news":n,
            "guards":{"market_ok":m.get("data_quality",{}).get("status")!="FAILED",
                      "news_ok":n.get("summary",{}).get("data_quality")!="FAILED",
                      "critical_news_verified":n.get("guard",{}).get("critical_news_verified",False)}}
if __name__=="__main__":
    a=(sys.argv[1] if len(sys.argv)>1 else "BTC").upper();h=int(sys.argv[2]) if len(sys.argv)>2 else 12
    print(json.dumps(build(a,h),ensure_ascii=False,separators=(",",":")))

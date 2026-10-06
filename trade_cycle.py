#!/usr/bin/env python3
import sys,json
from pathlib import Path
from datetime import datetime,timezone
import config,cooldown,decision_context,paper_execution,risk_engine
def parse_ts(x):
    try:return datetime.fromisoformat((x or "").replace("Z","+00:00"))
    except:return None
def prepare(asset,hours=12):
    c=decision_context.build(asset,hours);s=paper_execution.status()
    ts=parse_ts(c.get("market",{}).get("generated_at_utc"));age=(datetime.now(timezone.utc)-ts).total_seconds() if ts else 10**9
    guards={**c.get("guards",{}),"market_stale":age>config.STALE_MARKET_SECONDS,"cooldown":cooldown.status(asset),
            "trading_halted":s.get("trading_halted",False)}
    return {"status":"READY_FOR_ASTRA" if c.get("status")=="OK" else "FAILED","asset":asset,"decision_context":c,
            "account_state":{"initial_equity":s.get("initial_equity"),"equity":s.get("account_equity"),
            "daily_pnl":s.get("daily_realized_pnl",0),"open_positions":s.get("open_positions_count",0),
            "current_exposure_usd":s.get("current_exposure_usd",0)},"guards":guards}
def execute(decision):
    a=str(decision.get("asset","")).upper();act=str(decision.get("action","")).upper()
    if act=="WAIT":return {"status":"NO_TRADE","reason":"ASTRA_WAIT"}
    p=prepare(a,12);g=p["guards"]
    if g.get("market_stale") or not g.get("market_ok"):return {"status":"REJECTED","reason":"MARKET_DATA_GUARD"}
    if not g.get("news_ok"):return {"status":"REJECTED","reason":"NEWS_DATA_GUARD"}
    if not g.get("critical_news_verified"):return {"status":"REJECTED","reason":"UNVERIFIED_HIGH_IMPACT_NEWS"}
    if g.get("cooldown",{}).get("active"):return {"status":"REJECTED","reason":"COOLDOWN_ACTIVE"}
    if g.get("trading_halted"):return {"status":"REJECTED","reason":"TRADING_HALTED"}
    rinput={**decision,"equity":p["account_state"]["equity"],"initial_equity":p["account_state"]["initial_equity"],
            "daily_pnl":p["account_state"]["daily_pnl"],"open_positions":p["account_state"]["open_positions"],
            "current_exposure_usd":p["account_state"]["current_exposure_usd"],
            "critical_news_verified":True}
    r=risk_engine.evaluate(rinput)
    if r.get("status")!="APPROVED":return {"status":"REJECTED","stage":"risk_engine","risk":r}
    r["take_profit_1"]=decision.get("take_profit_1");r["take_profit_2"]=decision.get("take_profit_2")
    path=Path(config.STATE_DIR)/f"risk_{a}.json";path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(r),encoding="utf-8")
    return paper_execution.open_position(path)
if __name__=="__main__":
    if sys.argv[1]=="prepare":print(json.dumps(prepare(sys.argv[2].upper(),int(sys.argv[3]) if len(sys.argv)>3 else 12),ensure_ascii=False))
    else:print(json.dumps(execute(json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))),ensure_ascii=False))

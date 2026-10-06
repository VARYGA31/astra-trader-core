#!/usr/bin/env python3
import sys,json,config
ALLOWED=set(config.ALLOWED_ASSETS)
def reject(r,extra=None):
    x={"status":"REJECTED","reason":r}
    if extra:x.update(extra)
    return x
def evaluate(d):
    a=str(d.get("asset","")).upper();act=str(d.get("action","")).upper()
    eq=float(d.get("equity",config.INITIAL_EQUITY));init=float(d.get("initial_equity",config.INITIAL_EQUITY))
    if a not in ALLOWED:return reject("TRADE_NOT_ALLOWED")
    if act not in {"LONG","SHORT"}:return reject("NO_ACTION_TO_EXECUTE")
    if str(d.get("data_quality","FAILED")).upper()=="FAILED":return reject("MARKET_DATA_FAILED")
    if not bool(d.get("critical_news_verified",False)):return reject("UNVERIFIED_HIGH_IMPACT_NEWS")
    if d.get("entry") is None:return reject("ENTRY_REQUIRED")
    if d.get("stop_loss") is None:return reject("STOP_LOSS_REQUIRED")
    e=float(d["entry"]);s=float(d["stop_loss"])
    if e<=0 or s<=0:return reject("INVALID_PRICE")
    if act=="LONG" and s>=e:return reject("INVALID_STOP_FOR_LONG")
    if act=="SHORT" and s<=e:return reject("INVALID_STOP_FOR_SHORT")
    dd=max(0,(init-eq)/init) if init>0 else 1
    if dd>=config.MAX_DRAWDOWN_PCT:return reject("MAX_DRAWDOWN_REACHED",{"trading_halted":True})
    if float(d.get("daily_pnl",0))<=-(init*config.DAILY_LOSS_LIMIT_PCT):return reject("DAILY_LOSS_LIMIT_REACHED")
    if int(d.get("open_positions",0))>=config.MAX_OPEN_POSITIONS:return reject("MAX_OPEN_POSITIONS_REACHED")
    mult=.25 if dd>=.20 else .5 if dd>=.15 else .75 if dd>=.10 else 1
    dist=abs(e-s)/e;risk_pct=min(config.NORMAL_RISK_PCT*mult,config.HARD_RISK_PCT);risk=eq*risk_pct
    lev=min(max(float(d.get("leverage",config.DEFAULT_LEVERAGE)),1),config.MAX_LEVERAGE)
    if str(d.get("volatility_regime","NORMAL")).upper() in {"HIGH","EXTREME"} or (lev>3 and float(d.get("confidence",0))<75):lev=3
    n=min(max(eq*config.NORMAL_POSITION_PCT,risk/dist),eq*config.MAX_POSITION_PCT)
    if n*dist>risk:n=risk/dist
    n=min(n,max(0,eq*config.MAX_TOTAL_EXPOSURE_PCT-float(d.get("current_exposure_usd",0))))
    if n<=0:return reject("NO_EXPOSURE_CAPACITY")
    return {"status":"APPROVED","asset":a,"action":act,"entry":e,"stop_loss":s,"position_notional_usd":n,
            "actual_risk_usd":n*dist,"actual_risk_pct":n*dist/eq,"leverage":lev,"margin_required_usd":n/lev}
if __name__=="__main__":
    d=json.load(open(sys.argv[1],encoding="utf-8")) if len(sys.argv)>1 else json.load(sys.stdin)
    print(json.dumps(evaluate(d),ensure_ascii=False,separators=(",",":")))

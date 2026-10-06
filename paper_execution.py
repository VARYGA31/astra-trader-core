#!/usr/bin/env python3
import sys,json,uuid
from pathlib import Path
from datetime import datetime,timezone
import config
DIR=Path(config.STATE_DIR);FILE=DIR/"paper_state.json";ALLOWED=set(config.ALLOWED_ASSETS)
def now():return datetime.now(timezone.utc).isoformat()
def today():return datetime.now(timezone.utc).date().isoformat()
def base(eq):return {"initial_equity":eq,"account_equity":eq,"free_cash":eq,"realized_pnl":0.0,"daily_realized_pnl":0.0,
"daily_pnl_date":today(),"open_positions":[],"closed_positions":[],"trading_halted":False,"created_at_utc":now(),"updated_at_utc":now()}
def load():
    DIR.mkdir(parents=True,exist_ok=True)
    if not FILE.exists():return base(config.INITIAL_EQUITY)
    s=json.loads(FILE.read_text(encoding="utf-8"))
    if s.get("daily_pnl_date")!=today():s["daily_realized_pnl"]=0.0;s["daily_pnl_date"]=today()
    return s
def save(s):
    DIR.mkdir(parents=True,exist_ok=True);s["updated_at_utc"]=now();tmp=FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding="utf-8");tmp.replace(FILE)
def dd(s):return max(0,(s["initial_equity"]-s["account_equity"])/s["initial_equity"])
def halt(s):
    if dd(s)>=config.MAX_DRAWDOWN_PCT:s["trading_halted"]=True
    return s["trading_halted"]
def init_state(eq=None,force=False):
    if FILE.exists() and not force:return {"status":"EXISTS","state":load()}
    s=base(float(eq or config.INITIAL_EQUITY));save(s);return {"status":"INITIALIZED","state":s}
def status():
    s=load();halt(s);save(s)
    return {"status":"OK","initial_equity":s["initial_equity"],"account_equity":s["account_equity"],"free_cash":s["free_cash"],
    "realized_pnl":s["realized_pnl"],"daily_realized_pnl":s["daily_realized_pnl"],"open_positions":s["open_positions"],
    "open_positions_count":len(s["open_positions"]),"current_exposure_usd":sum(p["remaining_notional_usd"] for p in s["open_positions"]),
    "margin_used_usd":sum(p["remaining_margin_usd"] for p in s["open_positions"]),"closed_positions_count":len(s["closed_positions"]),
    "drawdown_pct":dd(s),"trading_halted":s["trading_halted"],"state_file":str(FILE)}
def open_position(path):
    s=load();r=json.loads(Path(path).read_text(encoding="utf-8"))
    if halt(s):return {"status":"REJECTED","reason":"TRADING_HALTED"}
    if r.get("status")!="APPROVED":return {"status":"REJECTED","reason":"RISK_NOT_APPROVED"}
    a=r["asset"]
    if a not in ALLOWED:return {"status":"REJECTED","reason":"TRADE_NOT_ALLOWED"}
    if len(s["open_positions"])>=config.MAX_OPEN_POSITIONS:return {"status":"REJECTED","reason":"MAX_OPEN_POSITIONS"}
    if any(p["asset"]==a for p in s["open_positions"]):return {"status":"REJECTED","reason":"DUPLICATE_ASSET_POSITION"}
    m=float(r["margin_required_usd"])
    if m>s["free_cash"]:return {"status":"REJECTED","reason":"INSUFFICIENT_FREE_CASH"}
    n=float(r["position_notional_usd"])
    p={"id":str(uuid.uuid4())[:8],"asset":a,"side":r["action"],"entry":float(r["entry"]),"stop_loss":float(r["stop_loss"]),
       "take_profit_1":r.get("take_profit_1"),"take_profit_2":r.get("take_profit_2"),"initial_notional_usd":n,
       "remaining_notional_usd":n,"leverage":float(r["leverage"]),"initial_margin_usd":m,"remaining_margin_usd":m,
       "tp1_taken":False,"opened_at_utc":now(),"status":"OPEN","fills":[]}
    s["free_cash"]-=m;s["open_positions"].append(p);save(s);return {"status":"PAPER_OPENED","position":p}
def pnl(side,entry,exit,n):return n*((exit-entry)/entry) if side=="LONG" else n*((entry-exit)/entry)
def partial_close(pid,exit_price,fraction,reason):
    s=load();p=next((x for x in s["open_positions"] if x["id"]==pid),None)
    if not p:return {"status":"REJECTED","reason":"POSITION_NOT_FOUND"}
    f=min(max(float(fraction),0),1);n=p["remaining_notional_usd"]*f;m=p["remaining_margin_usd"]*f
    q=pnl(p["side"],float(p["entry"]),float(exit_price),n)
    s["free_cash"]+=m+q;s["account_equity"]+=q;s["realized_pnl"]+=q;s["daily_realized_pnl"]+=q
    p["remaining_notional_usd"]-=n;p["remaining_margin_usd"]-=m
    if reason=="TAKE_PROFIT_1":p["tp1_taken"]=True
    fill={"exit_price":float(exit_price),"closed_notional_usd":n,"realized_pnl_usd":q,"reason":reason,"time_utc":now()};p["fills"].append(fill)
    if f>=.999999 or p["remaining_notional_usd"]<=1e-9:
        p["status"]="CLOSED";p["closed_at_utc"]=now();p["realized_pnl_usd"]=sum(x["realized_pnl_usd"] for x in p["fills"])
        s["open_positions"]=[x for x in s["open_positions"] if x["id"]!=pid];s["closed_positions"].append(p)
    halt(s);save(s)
    return {"status":"PAPER_CLOSED" if p["status"]=="CLOSED" else "PAPER_PARTIAL_CLOSE","position":p,"fill":fill}
if __name__=="__main__":
    c=sys.argv[1]
    if c=="init":o=init_state(float(sys.argv[2]) if len(sys.argv)>2 else None,"--force" in sys.argv)
    elif c=="status":o=status()
    elif c=="open":o=open_position(sys.argv[2])
    elif c=="partial_close":o=partial_close(sys.argv[2],float(sys.argv[3]),float(sys.argv[4]),sys.argv[5] if len(sys.argv)>5 else "MANUAL")
    else:o={"status":"REJECTED","reason":"UNKNOWN_COMMAND"}
    print(json.dumps(o,ensure_ascii=False,separators=(",",":")))

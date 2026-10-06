#!/usr/bin/env python3
import json,math,statistics
from pathlib import Path
from collections import defaultdict
from datetime import datetime,timezone
import config
DIR=Path(config.STATE_DIR);JOURNAL=DIR/"trade_journal.jsonl";STATE=DIR/"paper_state.json"
def stamp():return datetime.now(timezone.utc).isoformat()
def append_event(e):
    DIR.mkdir(parents=True,exist_ok=True);x={"timestamp_utc":stamp(),**e}
    with JOURNAL.open("a",encoding="utf-8") as f:f.write(json.dumps(x,ensure_ascii=False)+"\n")
    return x
def closed():
    try:return json.loads(STATE.read_text(encoding="utf-8")).get("closed_positions",[])
    except:return []
def stats(ts):
    p=[float(t.get("realized_pnl_usd",0)) for t in ts];w=[x for x in p if x>0];l=[x for x in p if x<0];gp=sum(w);gl=abs(sum(l))
    return {"trades":len(p),"wins":len(w),"losses":len(l),"win_rate":len(w)/len(p) if p else 0,
            "avg_win_usd":statistics.mean(w) if w else 0,"avg_loss_usd":statistics.mean(l) if l else 0,
            "expectancy_usd_per_trade":statistics.mean(p) if p else 0,
            "profit_factor":gp/gl if gl else (math.inf if gp else None),"net_pnl_usd":sum(p)}
def summary():
    t=closed();d=defaultdict(list)
    for x in t:d[x.get("asset","UNKNOWN")].append(x)
    return {"generated_at_utc":stamp(),"overall":stats(t),"by_asset":{a:stats(v) for a,v in d.items()},"recent_closed_positions":t[-20:]}
if __name__=="__main__":print(json.dumps(summary(),ensure_ascii=False))

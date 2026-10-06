#!/usr/bin/env python3
import json,time,sys
from pathlib import Path
from datetime import datetime,timezone
import config
import news_snapshot

STATE=Path(config.STATE_DIR)/"news_seen.json"

def load_seen():
    try:return set(json.loads(STATE.read_text(encoding="utf-8")))
    except:return set()

def save_seen(s):
    STATE.parent.mkdir(parents=True,exist_ok=True)
    STATE.write_text(json.dumps(list(s)[-10000:]),encoding="utf-8")

def poll_once(hours=2):
    seen=load_seen();new=[];health={}
    for asset in config.ALLOWED_ASSETS:
        s=news_snapshot.snapshot(asset,hours);health[asset]=s.get("summary",{})
        for e in s.get("events",[]):
            k=asset+":"+e["id"]
            if k not in seen:
                seen.add(k);new.append(e)
    save_seen(seen)
    return {"status":"OK","polled_at_utc":datetime.now(timezone.utc).isoformat(),
            "new_events":new,"high_impact_new":[e for e in new if e.get("impact_hint")=="HIGH"],"health":health}

if __name__=="__main__":
    if len(sys.argv)>1 and sys.argv[1]=="watch":
        interval=int(sys.argv[2]) if len(sys.argv)>2 else config.NEWS_POLL_SECONDS
        while True:
            print(json.dumps(poll_once(),ensure_ascii=False,separators=(",",":")),flush=True);time.sleep(interval)
    else:
        print(json.dumps(poll_once(),ensure_ascii=False,separators=(",",":")))

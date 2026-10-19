#!/usr/bin/env python3
import json,time,sys
from pathlib import Path
from datetime import datetime,timezone
import config
import news_snapshot
import news_cache

STATE=Path(config.STATE_DIR)/"news_seen.json"

def load_seen():
    try:return set(json.loads(STATE.read_text(encoding="utf-8")))
    except:return set()

def save_seen(s):
    STATE.parent.mkdir(parents=True,exist_ok=True)
    STATE.write_text(json.dumps(list(s)[-10000:]),encoding="utf-8")

def poll_once(hours=2,assets=None):
    """Poll only assets relevant to the current trading mode.

    This keeps MICRO from fetching XAU macro/news and lets PAUSED/NORMAL still
    request the broader set when needed.
    """
    seen=load_seen();new=[];health={}
    selected=tuple(dict.fromkeys(str(a).upper() for a in (assets or config.ALLOWED_ASSETS)))
    for asset in selected:
        s=news_snapshot.snapshot(asset,hours);health[asset]=s.get("summary",{})
        news_cache.put(asset,s)
        for e in s.get("events",[]):
            k=asset+":"+e["id"]
            if k not in seen:
                seen.add(k);new.append(e)
    save_seen(seen)
    return {"status":"OK","polled_at_utc":datetime.now(timezone.utc).isoformat(),
            "assets":list(selected),
            "new_events":new,"high_impact_new":[e for e in new if e.get("impact_hint")=="HIGH"],"health":health}

if __name__=="__main__":
    if len(sys.argv)>1 and sys.argv[1]=="watch":
        interval=int(sys.argv[2]) if len(sys.argv)>2 else config.NEWS_POLL_SECONDS
        while True:
            print(json.dumps(poll_once(),ensure_ascii=False,separators=(",",":")),flush=True);time.sleep(interval)
    else:
        print(json.dumps(poll_once(),ensure_ascii=False,separators=(",",":")))

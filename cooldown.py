#!/usr/bin/env python3
import json
from pathlib import Path
from datetime import datetime,timezone,timedelta
import config
FILE=Path(config.STATE_DIR)/"cooldowns.json"
def now():return datetime.now(timezone.utc)
def load():
    try:return json.loads(FILE.read_text(encoding="utf-8"))
    except:return {}
def save(d):
    FILE.parent.mkdir(parents=True,exist_ok=True);FILE.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding="utf-8")
def set_cooldown(asset,seconds=None,reason="POST_TRADE"):
    d=load();u=now()+timedelta(seconds=int(seconds or config.COOLDOWN_SECONDS));d[asset]={"until_utc":u.isoformat(),"reason":reason};save(d);return {"active":True,**d[asset]}
def status(asset):
    x=load().get(asset)
    if not x:return {"active":False}
    try:a=now()<datetime.fromisoformat(x["until_utc"])
    except:a=False
    return {"active":a,**x}

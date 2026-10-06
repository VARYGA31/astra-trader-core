#!/usr/bin/env python3
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
import config

STATE_DIR = Path(config.STATE_DIR)
FILE = STATE_DIR / "cooldowns.json"

def now():
    return datetime.now(timezone.utc)

def load():
    if not FILE.exists():
        return {}
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save(data):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def set_cd(asset, seconds, reason):
    d = load()
    until = now() + timedelta(seconds=seconds)
    d[asset] = {"until_utc": until.isoformat(), "reason": reason}
    save(d)
    return d[asset]

def get_cd(asset):
    d = load()
    x = d.get(asset)
    if not x:
        return {"active": False}
    try:
        until = datetime.fromisoformat(x["until_utc"])
    except Exception:
        return {"active": False}
    active = now() < until
    return {"active": active, **x}

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    asset = (sys.argv[2] if len(sys.argv) > 2 else "BTC").upper()
    if cmd == "set":
        seconds = int(sys.argv[3]) if len(sys.argv) > 3 else 900
        reason = sys.argv[4] if len(sys.argv) > 4 else "POST_TRADE"
        print(json.dumps(set_cd(asset, seconds, reason), ensure_ascii=False))
    else:
        print(json.dumps(get_cd(asset), ensure_ascii=False))

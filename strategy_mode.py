#!/usr/bin/env python3
"""Persistent single-active-strategy controller.

NORMAL and SCALP are mutually exclusive. PAUSED stops only new entries;
position monitoring and exchange-side protection keep running.
"""
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
import config

FILE = Path(config.STATE_DIR) / "strategy_mode.json"
ALLOWED = {"NORMAL", "SCALP", "PAUSED"}
RUNTIME_LOCK = threading.RLock()

def _now():
    return datetime.now(timezone.utc).isoformat()

def _default():
    mode = str(config.DEFAULT_STRATEGY_MODE or "NORMAL").upper()
    if mode not in ALLOWED:
        mode = "NORMAL"
    return {"mode": mode, "changed_at_utc": _now(), "changed_by": "DEFAULT"}

def load():
    try:
        d=json.loads(FILE.read_text(encoding="utf-8"))
        mode=str(d.get("mode") or "").upper()
        if mode not in ALLOWED:
            raise ValueError("invalid mode")
        return d
    except Exception:
        return _default()

def get_mode():
    return str(load().get("mode") or "NORMAL").upper()

def status():
    d=load()
    d["allowed_modes"]=["NORMAL","SCALP","PAUSED"]
    return d

def set_mode(mode, changed_by="SYSTEM"):
    mode=str(mode or "").upper().strip()
    if mode not in ALLOWED:
        raise ValueError(f"INVALID_STRATEGY_MODE:{mode}")
    row={"mode":mode,"changed_at_utc":_now(),"changed_by":str(changed_by)}
    FILE.parent.mkdir(parents=True,exist_ok=True)
    tmp=FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding="utf-8")
    tmp.replace(FILE)
    return status()

def switch_check(current, target, open_positions):
    current=str(current or "NORMAL").upper()
    target=str(target or "").upper()
    if target not in ALLOWED:
        return {"allowed":False,"reason":"INVALID_MODE"}
    if target==current:
        return {"allowed":True,"reason":"ALREADY_ACTIVE"}
    if target=="PAUSED":
        return {"allowed":True,"reason":"PAUSE_ALWAYS_ALLOWED"}
    if int(open_positions or 0)>0:
        return {"allowed":False,"reason":"OPEN_POSITION_EXISTS"}
    return {"allowed":True,"reason":"OK"}

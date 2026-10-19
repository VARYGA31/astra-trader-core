#!/usr/bin/env python3
"""Persistent single-active trading-mode controller.

Only NORMAL and MICRO are tradable modes.
PAUSED is a technical safety mode that blocks new entries while position
monitoring and exchange-side protection remain active.

Legacy SCALP/AUTO mode values are migrated to NORMAL on read.
"""
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
import config

FILE = Path(config.STATE_DIR) / "strategy_mode.json"
ALLOWED = {"NORMAL", "MICRO", "PAUSED"}
RETIRED = {"SCALP", "AUTO"}
RUNTIME_LOCK = threading.RLock()

def _now():
    return datetime.now(timezone.utc).isoformat()

def _atomic_write(row):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(FILE)

def _default():
    mode = str(config.DEFAULT_STRATEGY_MODE or "NORMAL").upper()
    if mode not in ALLOWED:
        mode = "NORMAL"
    return {"mode": mode, "changed_at_utc": _now(), "changed_by": "DEFAULT"}

def load():
    try:
        d = json.loads(FILE.read_text(encoding="utf-8"))
        mode = str(d.get("mode") or "").upper()
        if mode in RETIRED:
            row = {
                "mode":"NORMAL",
                "changed_at_utc":_now(),
                "changed_by":f"MIGRATION_FROM_{mode}",
            }
            _atomic_write(row)
            return row
        if mode not in ALLOWED:
            raise ValueError("invalid mode")
        return d
    except Exception:
        return _default()

def get_mode():
    return str(load().get("mode") or "NORMAL").upper()

def status():
    d = load()
    d["allowed_modes"] = ["NORMAL","MICRO","PAUSED"]
    d["retired_modes"] = ["SCALP","AUTO"]
    return d

def set_mode(mode, changed_by="SYSTEM"):
    mode = str(mode or "").upper().strip()
    if mode not in ALLOWED:
        raise ValueError(f"INVALID_STRATEGY_MODE:{mode}")
    row = {"mode":mode,"changed_at_utc":_now(),"changed_by":str(changed_by)}
    _atomic_write(row)
    return status()

def switch_check(current, target, open_positions):
    current = str(current or "NORMAL").upper()
    target = str(target or "").upper()
    if target not in ALLOWED:
        return {"allowed":False,"reason":"INVALID_MODE"}
    if target == current:
        return {"allowed":True,"reason":"ALREADY_ACTIVE"}
    if target == "PAUSED":
        return {"allowed":True,"reason":"PAUSE_ALWAYS_ALLOWED"}
    if int(open_positions or 0) > 0:
        return {"allowed":False,"reason":"OPEN_POSITION_EXISTS"}
    return {"allowed":True,"reason":"OK"}

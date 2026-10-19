#!/usr/bin/env python3
"""Thread-safe in-process cache for verified news snapshots."""
import threading, time

LOCK=threading.RLock()
DATA={}

def put(asset,snapshot):
    with LOCK:
        DATA[str(asset).upper()]={"at":time.time(),"snapshot":snapshot}

def get(asset,max_age_seconds):
    with LOCK:
        row=DATA.get(str(asset).upper())
        if not row:return None
        if time.time()-float(row.get("at") or 0)>float(max_age_seconds):
            return None
        return row.get("snapshot")

def health():
    with LOCK:
        now=time.time()
        return {
            a:{"age_seconds":round(now-float(x.get("at") or 0),3)}
            for a,x in DATA.items()
        }

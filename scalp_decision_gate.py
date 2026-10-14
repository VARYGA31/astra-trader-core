#!/usr/bin/env python3
import json
from datetime import datetime, timezone
from pathlib import Path
import config
import scalp_gate

STATE_FILE=Path(config.STATE_DIR)/"scalp_decision_gate_state.json"

def _load():
    try:return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:return {}

def _save(d):
    STATE_FILE.parent.mkdir(parents=True,exist_ok=True)
    t=STATE_FILE.with_suffix(".tmp")
    t.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding="utf-8")
    t.replace(STATE_FILE)

def _high_event(package):
    for e in package.get("decision_context",{}).get("news",{}).get("events",[]):
        if e.get("impact_hint")=="HIGH" and e.get("trade_usable"):
            return e
    return None

def _age_minutes(e):
    if not e:return None
    try:
        dt=datetime.fromisoformat((e.get("published_at_utc") or "").replace("Z","+00:00"))
        return (datetime.now(timezone.utc)-dt).total_seconds()/60
    except Exception:return None

def evaluate(package,force_event=False):
    asset=str(package.get("asset","")).upper()
    if asset not in set(config.SCALP_ALLOWED_ASSETS):
        return {"call_model":False,"reason":"SCALP_ASSET_NOT_ALLOWED"}
    g=package.get("guards",{})
    if (
        g.get("market_stale") or not g.get("market_ok") or not g.get("news_ok")
        or not g.get("critical_news_verified") or g.get("trading_halted")
        or g.get("cooldown",{}).get("active") or g.get("loss_streak_pause",{}).get("active")
    ):
        return {"call_model":False,"reason":"GUARD_BLOCK","guards":g}
    if int(package.get("account_state",{}).get("open_positions",0))>=config.MAX_OPEN_POSITIONS:
        return {"call_model":False,"reason":"MAX_OPEN_POSITIONS"}

    ev=_high_event(package)
    age=_age_minutes(ev)
    if age is not None and age<config.SCALP_NEWS_SETTLE_MINUTES:
        return {
            "call_model":False,"reason":"SCALP_HIGH_NEWS_SETTLE",
            "news_age_minutes":age,"settle_minutes":config.SCALP_NEWS_SETTLE_MINUTES,
            "event":{k:ev.get(k) for k in ("id","source","title","event_type","impact_hint")},
        }

    gate=scalp_gate.evaluate(package)
    if not gate.get("passed"):
        return {"call_model":False,"reason":gate.get("reason","SCALP_NOT_ALIGNED"),"mtf":gate}
    chase=scalp_gate.entry_guard(package,gate.get("direction"))
    if chase.get("blocked"):
        return {"call_model":False,"reason":chase.get("reason"),"mtf":gate,"chase_guard":chase}

    st=_load(); old=st.get(asset,{})
    candle=gate.get("trigger_candle_id")
    new_trigger=candle is not None and candle!=old.get("last_trigger_candle_id")
    call=bool(new_trigger)
    if call:
        st[asset]={
            "last_trigger_candle_id":candle,
            "last_direction":gate.get("direction"),
            "last_quality":gate.get("quality"),
            "last_called_at_utc":datetime.now(timezone.utc).isoformat(),
        }
        _save(st)
    return {
        "call_model":call,
        "reason":"MODEL_GATE_PASS" if call else "SAME_5M_TRIGGER",
        "allowed_direction":gate.get("direction"),
        "mtf_quality":gate.get("quality"),
        "mtf_mode":"SCALP",
        "new_trigger_candle":new_trigger,
        "mtf":gate,
        "chase_guard":chase,
    }

#!/usr/bin/env python3
import json
from pathlib import Path
from datetime import datetime, timezone
import config

JOURNAL=Path(config.STATE_DIR)/"trade_journal.jsonl"

def _ts(x):
    try:
        return datetime.fromisoformat((x or "").replace("Z","+00:00"))
    except Exception:
        return None

def status(strategy_mode="NORMAL"):
    mode=str(strategy_mode or "NORMAL").upper()
    limit=config.SCALP_LOSS_STREAK_LIMIT if mode=="SCALP" else config.LOSS_STREAK_LIMIT
    pause_seconds=config.SCALP_LOSS_STREAK_PAUSE_SECONDS if mode=="SCALP" else config.LOSS_STREAK_PAUSE_SECONDS
    if limit <= 0:
        return {"active":False,"reason":"DISABLED","strategy_mode":mode}

    try:
        lines=JOURNAL.read_text(encoding="utf-8").splitlines()
    except Exception:
        return {"active":False,"reason":"NO_JOURNAL"}

    closes=[]
    seen=set()
    for line in lines:
        try:
            e=json.loads(line)
        except Exception:
            continue
        if e.get("event")!="OKX_POSITION_CLOSED":
            continue
        event_mode=str(e.get("strategy_mode") or "NORMAL").upper()
        if event_mode!=mode:
            continue
        key=e.get("close_event_id") or f"{e.get('asset')}:{e.get('order_id')}:{e.get('opened_at_utc')}"
        if key in seen:
            continue
        seen.add(key)
        closes.append(e)

    if len(closes)<limit:
        return {"active":False,"reason":"INSUFFICIENT_CLOSED_TRADES","recent_count":len(closes)}

    recent=closes[-limit:]
    if not all(float(x.get("pnl_usd") or 0)<0 for x in recent):
        return {"active":False,"reason":"NO_LOSS_STREAK"}

    last_ts=_ts(recent[-1].get("timestamp_utc"))
    if not last_ts:
        return {"active":False,"reason":"LOSS_STREAK_NO_TIMESTAMP"}

    elapsed=(datetime.now(timezone.utc)-last_ts).total_seconds()
    remaining=max(0,int(pause_seconds-elapsed))
    return {
        "active":remaining>0,
        "reason":"LOSS_STREAK_PAUSE" if remaining>0 else "LOSS_STREAK_PAUSE_EXPIRED",
        "strategy_mode":mode,
        "losses":len(recent),
        "remaining_seconds":remaining,
        "recent":[
            {"asset":x.get("asset"),"pnl_usd":x.get("pnl_usd"),"reason":x.get("reason"),"timestamp_utc":x.get("timestamp_utc")}
            for x in recent
        ],
    }

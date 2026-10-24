#!/usr/bin/env python3
"""Unified OpenAI model budget + circuit breaker for ASTRA.

All paid model-call paths must reserve budget here before touching the API and
record success/error afterwards. This layer never changes trade risk, leverage,
position sizing, or execution. It only controls whether a paid model opinion is
available.
"""
import json
import threading
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import config

LOCK=threading.RLock()
DIR=Path(config.STATE_DIR)
USAGE_FILE=DIR/"openai_usage.jsonl"
EVENT_FILE=DIR/"model_budget_events.jsonl"
STATE_FILE=DIR/"model_budget_state.json"

def now():
    return datetime.now(timezone.utc)

def _parse_ts(x):
    try:
        return datetime.fromisoformat(str(x or "").replace("Z","+00:00"))
    except Exception:
        return None

def _atomic_json(path,payload):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(f"{path.name}.{threading.get_ident()}.{int(time.time()*1_000_000)}.tmp")
    tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    tmp.replace(path)

def _load_state():
    try:
        x=json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return x if isinstance(x,dict) else {}
    except Exception:
        return {}

def _save_state(x):
    _atomic_json(STATE_FILE,x)

def _append(path,row):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("a",encoding="utf-8") as f:
        f.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")

def _read_usage():
    rows=[]
    try:
        with USAGE_FILE.open("r",encoding="utf-8") as f:
            for line in f:
                try:
                    x=json.loads(line)
                    if isinstance(x,dict):rows.append(x)
                except Exception:
                    continue
    except Exception:
        pass
    return rows

def _pricing(model):
    m=str(model or "").lower()
    # Standard API rates per 1M text tokens. Keep this mapping local so old
    # Astra rows and new Sol rows are costed correctly in the same usage file.
    if "gpt-6-astra" in m:
        return 10.0,1.0,50.0
    if "gpt-6.1-sol" in m:
        return 2.0,0.10,10.0
    if "gpt-6-luna" in m:
        return 0.10,0.01,0.50
    return (
        float(config.MODEL_PRICE_INPUT_USD_PER_M),
        float(config.MODEL_PRICE_CACHED_INPUT_USD_PER_M),
        float(config.MODEL_PRICE_OUTPUT_USD_PER_M),
    )

def _row_cost(row):
    i=int(row.get("input_tokens") or 0)
    ci=min(i,int(row.get("cached_input_tokens") or 0))
    o=int(row.get("output_tokens") or 0)
    pin,pcache,pout=_pricing(row.get("model"))
    return ((i-ci)*pin+ci*pcache+o*pout)/1_000_000.0

def _clean_pending(state):
    utc=now()
    pending=[]
    for x in state.get("pending") or []:
        exp=_parse_ts(x.get("expires_at_utc"))
        if exp and exp>utc:
            pending.append(x)
    state["pending"]=pending
    return state

def usage_today():
    with LOCK:
        d=now().date()
        rows=[]
        for x in _read_usage():
            ts=_parse_ts(x.get("timestamp_utc"))
            if ts and ts.date()==d:
                rows.append(x)
        calls=len(rows)
        inp=sum(int(x.get("input_tokens") or 0) for x in rows)
        cached=sum(int(x.get("cached_input_tokens") or 0) for x in rows)
        out=sum(int(x.get("output_tokens") or 0) for x in rows)
        total=sum(int(x.get("total_tokens") or ((x.get("input_tokens") or 0)+(x.get("output_tokens") or 0))) for x in rows)
        cost=sum(_row_cost(x) for x in rows)
        by_model={}
        by_purpose={}
        for x in rows:
            m=str(x.get("model") or "UNKNOWN")
            p=str(x.get("purpose") or x.get("strategy_mode") or "UNKNOWN")
            by_model[m]=by_model.get(m,0)+1
            by_purpose[p]=by_purpose.get(p,0)+1
        return {
            "date_utc":str(d),
            "calls":calls,
            "input_tokens":inp,
            "cached_input_tokens":cached,
            "output_tokens":out,
            "total_tokens":total,
            "estimated_cost_usd":round(cost,6),
            "by_model":by_model,
            "by_purpose":by_purpose,
        }

def _circuit(state):
    c=state.get("circuit") or {}
    until=_parse_ts(c.get("until_utc"))
    active=bool(until and until>now())
    return {
        "active":active,
        "kind":c.get("kind") if active else None,
        "reason":c.get("reason") if active else None,
        "until_utc":c.get("until_utc") if active else None,
        "opened_at_utc":c.get("opened_at_utc") if active else None,
    }

def apply_key_rotation_marker():
    """Apply an operator-confirmed API key rotation exactly once.

    The marker is non-secret and must be changed only when OPENAI_API_KEY is
    intentionally rotated. A changed marker may clear an AUTH_ERROR circuit,
    but never quota, rate-limit, or generic API circuits.
    """
    marker=str(getattr(config,"MODEL_KEY_ROTATION_MARKER","") or "").strip()
    if not marker:
        return {"status":"NO_MARKER","changed":False,"cleared_auth_circuit":False}

    with LOCK:
        state=_clean_pending(_load_state())
        previous=str(state.get("key_rotation_marker") or "")
        if previous==marker:
            return {"status":"UNCHANGED","changed":False,"cleared_auth_circuit":False}

        circuit=state.get("circuit") or {}
        cleared=bool(circuit.get("kind")=="AUTH_ERROR")
        if cleared:
            state["circuit"]={}
        state["key_rotation_marker"]=marker
        state["key_rotation_applied_at_utc"]=now().isoformat()
        _save_state(state)
        _append(EVENT_FILE,{
            "timestamp_utc":now().isoformat(),
            "event":"MODEL_KEY_ROTATION_MARKER_APPLIED",
            "cleared_auth_circuit":cleared,
        })
        return {"status":"APPLIED","changed":True,"cleared_auth_circuit":cleared}

def summary():
    with LOCK:
        state=_clean_pending(_load_state())
        u=usage_today()
        c=_circuit(state)
        pending=len(state.get("pending") or [])
        hard_calls=max(1,int(config.MODEL_DAILY_MAX_CALLS))
        reserve=max(0,min(hard_calls,int(config.MODEL_EMERGENCY_RESERVE_CALLS)))
        hard_usd=max(0.0,float(config.MODEL_DAILY_MAX_USD))
        spent=float(u.get("estimated_cost_usd") or 0.0)
        status="OK"
        if c["active"]:
            status="OFFLINE_QUOTA" if c["kind"]=="CREDIT_EXHAUSTED" else "CIRCUIT_OPEN"
        elif u["calls"]+pending>=hard_calls:
            status="DAILY_CALL_CAP"
        elif hard_usd>0 and spent>=hard_usd:
            status="DAILY_COST_CAP"
        return {
            "status":status,
            "model":config.OPENAI_MODEL,
            "reasoning_effort":config.OPENAI_REASONING_EFFORT,
            "daily":{
                **u,
                "max_calls":hard_calls,
                "normal_call_limit":max(0,hard_calls-reserve),
                "emergency_reserve_calls":reserve,
                "calls_remaining":max(0,hard_calls-u["calls"]-pending),
                "max_cost_usd":hard_usd if hard_usd>0 else None,
                "cost_remaining_usd":round(max(0.0,hard_usd-spent),6) if hard_usd>0 else None,
                "pending_reservations":pending,
            },
            "circuit":c,
            "max_output_tokens":int(config.MODEL_MAX_OUTPUT_TOKENS),
            "estimated_next_call_usd":float(config.MODEL_ESTIMATED_NEXT_CALL_USD),
        }

def before_call(purpose,asset=None,priority="normal",model=None):
    with LOCK:
        state=_clean_pending(_load_state())
        u=usage_today()
        c=_circuit(state)
        if c["active"]:
            _save_state(state)
            return {"allowed":False,"reason":"MODEL_CIRCUIT_OPEN","summary":summary()}

        pending=len(state.get("pending") or [])
        hard_calls=max(1,int(config.MODEL_DAILY_MAX_CALLS))
        reserve=max(0,min(hard_calls,int(config.MODEL_EMERGENCY_RESERVE_CALLS)))
        limit=hard_calls if priority=="emergency" else max(0,hard_calls-reserve)
        if u["calls"]+pending>=limit:
            _save_state(state)
            reason="DAILY_MODEL_CALL_CAP" if priority=="emergency" else "MODEL_EMERGENCY_RESERVE_PROTECTED"
            return {"allowed":False,"reason":reason,"summary":summary()}

        cap=max(0.0,float(config.MODEL_DAILY_MAX_USD))
        estimate=max(0.0,float(config.MODEL_ESTIMATED_NEXT_CALL_USD))
        projected=float(u.get("estimated_cost_usd") or 0.0)+(pending+1)*estimate
        if cap>0 and projected>cap:
            _save_state(state)
            return {"allowed":False,"reason":"DAILY_MODEL_COST_CAP","summary":summary()}

        rid=uuid.uuid4().hex[:16]
        created=now()
        reservation={
            "id":rid,
            "created_at_utc":created.isoformat(),
            "expires_at_utc":(created+timedelta(minutes=5)).isoformat(),
            "purpose":str(purpose),
            "asset":str(asset or ""),
            "priority":str(priority),
            "model":str(model or config.OPENAI_MODEL),
        }
        state.setdefault("pending",[]).append(reservation)
        _save_state(state)
        return {"allowed":True,"reason":"OK","reservation_id":rid,"summary":summary()}

def _release(state,reservation_id):
    state["pending"]=[x for x in (state.get("pending") or []) if x.get("id")!=reservation_id]
    return state

def record_success(response,reservation_id,purpose,asset=None,strategy_mode=None,model=None):
    with LOCK:
        state=_clean_pending(_load_state())
        state=_release(state,reservation_id)
        # Any successful paid request proves the API/key has recovered.
        if (state.get("circuit") or {}).get("kind"):
            state["circuit"]={}
        _save_state(state)

        u=getattr(response,"usage",None)
        if not u:
            return
        details=getattr(u,"input_tokens_details",None)
        cached=getattr(details,"cached_tokens",0) if details else 0
        row={
            "timestamp_utc":now().isoformat(),
            "purpose":str(purpose),
            "asset":str(asset or ""),
            "strategy_mode":str(strategy_mode or ""),
            "model":str(model or config.OPENAI_MODEL),
            "input_tokens":getattr(u,"input_tokens",None),
            "cached_input_tokens":cached,
            "output_tokens":getattr(u,"output_tokens",None),
            "total_tokens":getattr(u,"total_tokens",None),
        }
        _append(USAGE_FILE,row)

def _notify_once(kind,reason,until_utc,changed):
    if not changed:
        return
    try:
        import telegram_notifier
        telegram_notifier.notify_system(
            f"MODEL CIRCUIT: {kind}. {reason}. Paid model calls paused until {until_utc}. "
            "Risk/Execution remains deterministic; no live-trading setting changed.",
            level="RISK",
        )
    except Exception:
        pass

def record_error(exc,reservation_id,purpose,asset=None,model=None):
    with LOCK:
        state=_clean_pending(_load_state())
        state=_release(state,reservation_id)
        msg=str(exc or "")
        low=msg.lower()
        kind="API_ERROR"
        cooldown=max(30,int(config.MODEL_API_ERROR_COOLDOWN_SECONDS))
        if "credit_balance_exhausted" in low or "no credits remaining" in low or "insufficient_quota" in low:
            kind="CREDIT_EXHAUSTED"
            cooldown=max(60,int(config.MODEL_QUOTA_RETRY_SECONDS))
        elif "rate limit" in low or "ratelimit" in low or "429" in low:
            kind="RATE_LIMIT"
            cooldown=max(60,int(config.MODEL_RATE_LIMIT_COOLDOWN_SECONDS))
        elif "authentication" in low or "invalid api key" in low or "401" in low:
            kind="AUTH_ERROR"
            cooldown=max(300,int(config.MODEL_AUTH_ERROR_COOLDOWN_SECONDS))

        prev=_circuit(state)
        opened=now()
        until=opened+timedelta(seconds=cooldown)
        state["circuit"]={
            "kind":kind,
            "reason":msg[:800],
            "opened_at_utc":opened.isoformat(),
            "until_utc":until.isoformat(),
            "purpose":str(purpose),
            "asset":str(asset or ""),
            "model":str(model or config.OPENAI_MODEL),
        }
        _save_state(state)
        _append(EVENT_FILE,{
            "timestamp_utc":opened.isoformat(),
            "event":"MODEL_API_ERROR",
            "kind":kind,
            "purpose":str(purpose),
            "asset":str(asset or ""),
            "model":str(model or config.OPENAI_MODEL),
            "error":msg[:1000],
            "retry_at_utc":until.isoformat(),
        })
        changed=(not prev["active"]) or prev.get("kind")!=kind
        _notify_once(kind,msg[:220],until.isoformat(),changed)
        return {"kind":kind,"retry_at_utc":until.isoformat()}

def blocked_decision(asset,mode,reason):
    return {
        "asset":str(asset or "").upper(),
        "action":"WAIT",
        "entry":None,
        "stop_loss":None,
        "take_profit_1":None,
        "take_profit_2":None,
        "confidence":0.0,
        "data_quality":"MODEL_UNAVAILABLE",
        "volatility_regime":"UNKNOWN",
        "setup_type":"NONE",
        "reason":str(reason),
        "wait_category":"MODEL_UNAVAILABLE",
        "wait_is_hard_blocker":True,
        "strategy_mode":str(mode or "NORMAL").upper(),
        "_model_called":False,
        "_model_budget":summary(),
    }

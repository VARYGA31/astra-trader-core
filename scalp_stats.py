#!/usr/bin/env python3
"""Persistent forensic funnel for ASTRA SCALP.

Records one compact row per SCALP scan so /scalp_stats can explain where setups
are being filtered. Diagnostics never control execution.
"""
import json, threading
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
import config

FILE=Path(config.STATE_DIR)/"scalp_stats.jsonl"
LOCK=threading.Lock()

def _now(): return datetime.now(timezone.utc)

def _parse(x):
    try:return datetime.fromisoformat(str(x).replace("Z","+00:00"))
    except Exception:return None

def _compact_if_needed():
    try:
        if FILE.stat().st_size <= float(config.SCALP_STATS_LOG_MAX_MB)*1024*1024: return
        rows=FILE.read_text(encoding="utf-8").splitlines()
        keep=rows[len(rows)//2:]
        tmp=FILE.with_suffix(".tmp")
        tmp.write_text("\n".join(keep)+("\n" if keep else ""),encoding="utf-8")
        tmp.replace(FILE)
    except Exception: pass

def _blocker(gate):
    reason=str(gate.get("reason") or "UNKNOWN")
    mtf=gate.get("mtf") or {}
    primary=str(mtf.get("primary_blocker") or reason)
    mapping={
        "GUARD_BLOCK":"GUARD",
        "MAX_OPEN_POSITIONS":"MAX_OPEN_POSITIONS",
        "SCALP_HIGH_NEWS_SETTLE":"NEWS_SETTLE",
        "SCALP_SPREAD_TOO_WIDE":"SPREAD",
        "SCALP_VOLATILITY_OUT_OF_RANGE":"VOLATILITY",
        "SCALP_1H_REGIME_BLOCK":"1H_REGIME",
        "SCALP_15M_SETUP_BLOCK":"15M_SETUP",
        "SCALP_5M_TRIGGER_BLOCK":"5M_TRIGGER",
        "SCALP_5M_VOLUME_BLOCK":"5M_VOLUME",
        "SCALP_MICROSTRUCTURE_BLOCK":"MICROSTRUCTURE",
        "SCALP_QUALITY_BLOCK":"QUALITY",
        "SCALP_SHORT_CHASE":"CHASE",
        "SCALP_LONG_CHASE":"CHASE",
        "SCALP_CHASE_DATA_MISSING":"CHASE_DATA",
        "SAME_5M_TRIGGER":"SAME_TRIGGER",
    }
    return mapping.get(primary,mapping.get(reason,primary))

def record(package,gate,decision,execution,model_called=False):
    try:
        mtf=gate.get("mtf") or {}
        d=decision or {}; x=execution or {}
        row={
            "timestamp_utc":_now().isoformat(),
            "asset":package.get("asset"),
            "gate_call_model":bool(gate.get("call_model")),
            "gate_reason":gate.get("reason"),
            "blocker":None if gate.get("call_model") else _blocker(gate),
            "tier":gate.get("scalp_tier") or mtf.get("tier") or d.get("scalp_tier"),
            "direction":gate.get("allowed_direction") or mtf.get("direction"),
            "quality":gate.get("mtf_quality") if gate.get("mtf_quality") is not None else mtf.get("quality"),
            "model_called":bool(model_called),
            "model_action":d.get("action") if model_called else None,
            "model_confidence":d.get("confidence") if model_called else None,
            "model_wait_category":d.get("wait_category") if model_called and d.get("action")=="WAIT" else None,
            "execution_status":x.get("status"),
            "execution_reason":x.get("reason"),
        }
        FILE.parent.mkdir(parents=True,exist_ok=True)
        with LOCK:
            with FILE.open("a",encoding="utf-8") as f:f.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")
            _compact_if_needed()
    except Exception:
        pass

def _rows(hours):
    cutoff=_now()-timedelta(hours=float(hours))
    out=[]
    try:
        with LOCK:
            lines=FILE.read_text(encoding="utf-8").splitlines()
        for line in lines:
            try:r=json.loads(line)
            except Exception:continue
            dt=_parse(r.get("timestamp_utc"))
            if dt and dt>=cutoff: out.append(r)
    except Exception: pass
    return out

def summary(hours=None):
    hours=float(hours or config.SCALP_STATS_DEFAULT_HOURS)
    rows=_rows(hours)
    blockers=Counter(); tiers=Counter(); model_actions=Counter(); exec_reasons=Counter(); assets=Counter()
    model_calls=0; opened=0; fok_cancel=0; risk_reject=0; model_waits=0; model_trades=0
    for r in rows:
        assets[str(r.get("asset") or "?")]+=1
        if r.get("blocker"): blockers[str(r.get("blocker"))]+=1
        if r.get("tier"): tiers[str(r.get("tier"))]+=1
        if r.get("model_called"):
            model_calls+=1
            act=str(r.get("model_action") or "?")
            model_actions[act]+=1
            if act=="WAIT": model_waits+=1
            if act in {"LONG","SHORT"}: model_trades+=1
        status=str(r.get("execution_status") or "")
        reason=str(r.get("execution_reason") or "")
        if status=="OKX_DEMO_OPENED": opened+=1
        if reason=="ENTRY_FOK_NOT_FILLED": fok_cancel+=1
        if status=="REJECTED":
            exec_reasons[reason or "REJECTED"]+=1
            if reason and reason not in {"SCALP_NOT_ALIGNED_AT_EXECUTION","SCALP_SHORT_CHASE","SCALP_LONG_CHASE"}: risk_reject+=1
    return {
        "status":"OK",
        "hours":hours,
        "checks":len(rows),
        "by_asset":dict(assets),
        "gate_passes_by_tier":dict(tiers),
        "blockers":dict(blockers.most_common()),
        "model_calls":model_calls,
        "model_actions":dict(model_actions),
        "model_waits":model_waits,
        "model_trade_decisions":model_trades,
        "opened_trades":opened,
        "fok_not_filled":fok_cancel,
        "execution_rejections":dict(exec_reasons.most_common()),
        "risk_or_execution_rejects":risk_reject,
    }

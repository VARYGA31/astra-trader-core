#!/usr/bin/env python3
"""Persistent funnel diagnostics for ASTRA AUTO.

This module is passive: it never changes signals, risk, execution or model calls.
"""
import json
from collections import Counter,defaultdict
from datetime import datetime,timezone,timedelta
from pathlib import Path

import config

LOG=Path(config.STATE_DIR)/"adaptive_auto_events.jsonl"

def _now():
    return datetime.now(timezone.utc)

def _parse(x):
    try:
        return datetime.fromisoformat(str(x or "").replace("Z","+00:00"))
    except Exception:
        return None

def _compact_if_needed():
    try:
        max_mb=float(config.ADAPTIVE_AUTO_STATS_LOG_MAX_MB)
        if max_mb<=0 or not LOG.exists() or LOG.stat().st_size<=max_mb*1024*1024:
            return
        target=int(max_mb*1024*1024*0.5)
        with LOG.open("rb") as f:
            f.seek(max(0,LOG.stat().st_size-target))
            chunk=f.read()
        i=chunk.find(b"\n")
        if i>=0: chunk=chunk[i+1:]
        tmp=LOG.with_suffix(".tmp")
        tmp.write_bytes(chunk); tmp.replace(LOG)
    except Exception:
        pass

def record(run):
    try:
        run=run or {}
        plan=run.get("cost_plan") or {}
        scan=plan.get("local_scan") or {}
        best_scan=scan.get("best") or {}
        result=run.get("result") or {}
        best=result.get("best_opportunity") or {}
        decision=run.get("decision") or {}
        execution=run.get("execution") or {}
        status=str(run.get("status") or "UNKNOWN")
        action=str(decision.get("action") or best.get("action") or "WAIT").upper()
        model_called=(status=="OK")
        row={
            "timestamp_utc":_now().isoformat(),
            "status":status,
            "reason":run.get("reason"),
            "model_called":model_called,
            "cost_reason":plan.get("reason"),
            "local_triggered":bool(scan.get("triggered")),
            "local_best_asset":best_scan.get("asset"),
            "local_best_direction":best_scan.get("direction"),
            "local_best_score":best_scan.get("score"),
            "asset":decision.get("asset") or best.get("asset"),
            "action":action,
            "strategy":decision.get("strategy_mode") or best.get("strategy"),
            "scalp_tier":decision.get("scalp_tier") or best.get("scalp_tier"),
            "strategy_archetype":decision.get("strategy_archetype") or best.get("strategy_archetype"),
            "tournament_tier":decision.get("tournament_tier") or best.get("tournament_tier"),
            "tournament_risk_multiplier":decision.get("tournament_risk_multiplier") or best.get("tournament_risk_multiplier"),
            "confidence":decision.get("confidence") if decision.get("confidence") is not None else best.get("confidence"),
            "setup_quality":decision.get("adaptive_setup_quality") if decision.get("adaptive_setup_quality") is not None else best.get("setup_quality"),
            "execution_status":execution.get("status"),
            "execution_reason":execution.get("reason") or ((execution.get("risk") or {}).get("reason") if isinstance(execution.get("risk"),dict) else None),
            "opened":execution.get("status") in {"OKX_DEMO_OPENED","PAPER_OPENED","PAPER_POSITION_OPENED","OPENED"},
        }
        LOG.parent.mkdir(parents=True,exist_ok=True)
        with LOG.open("a",encoding="utf-8") as f:
            f.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")
        _compact_if_needed()
        return {"status":"OK"}
    except Exception as e:
        return {"status":"ERROR","error":str(e)}

def _rows(hours):
    since=_now()-timedelta(hours=float(hours))
    out=[]
    try:
        with LOG.open("r",encoding="utf-8") as f:
            for line in f:
                try: x=json.loads(line)
                except Exception: continue
                ts=_parse(x.get("timestamp_utc"))
                if ts and ts>=since: out.append(x)
    except Exception:
        pass
    return out

def summary(hours=None):
    hours=float(hours or config.ADAPTIVE_AUTO_STATS_DEFAULT_HOURS)
    rows=_rows(hours)
    cost_skips=Counter()
    exec_rejects=Counter()
    actions=Counter()
    strategies=Counter()
    assets=Counter()
    model_calls=0; model_waits=0; proposals=0; opened=0; local_triggers=0
    for x in rows:
        if x.get("local_triggered"): local_triggers+=1
        if x.get("model_called"):
            model_calls+=1
            a=str(x.get("action") or "WAIT").upper()
            actions[a]+=1
            if a=="WAIT": model_waits+=1
            if a in {"LONG","SHORT"}:
                proposals+=1
                assets[str(x.get("asset") or "UNKNOWN")]+=1
                strategies[str(x.get("strategy") or "UNKNOWN")]+=1
                if not x.get("opened"):
                    exec_rejects[str(x.get("execution_reason") or x.get("execution_status") or "UNKNOWN")]+=1
        else:
            cost_skips[str(x.get("cost_reason") or x.get("reason") or "UNKNOWN")]+=1
        if x.get("opened"): opened+=1
    return {
        "hours":hours,
        "cycles":len(rows),
        "local_triggers":local_triggers,
        "model_calls":model_calls,
        "model_waits":model_waits,
        "trade_proposals":proposals,
        "opened_trades":opened,
        "actions":dict(actions),
        "cost_skips":dict(cost_skips.most_common()),
        "execution_rejections":dict(exec_rejects.most_common()),
        "proposal_assets":dict(assets),
        "proposal_strategies":dict(strategies),
        "recent":rows[-10:],
    }

def telegram_text(hours=None):
    s=summary(hours)
    h=int(float(s["hours"]))
    lines=[
        f"📊 <b>ASTRA AUTO FUNNEL — {h}h</b>","",
        f"AUTO cycles: <b>{s['cycles']}</b>",
        f"Local strong triggers: <b>{s['local_triggers']}</b>",
        f"Astra calls: <b>{s['model_calls']}</b>",
        f"Astra WAIT: <b>{s['model_waits']}</b>",
        f"LONG/SHORT proposals: <b>{s['trade_proposals']}</b>",
        f"Opened trades: <b>{s['opened_trades']}</b>","",
        "<b>Cost-Smart skips:</b>",
    ]
    if s["cost_skips"]:
        for k,v in list(s["cost_skips"].items())[:6]:
            lines.append(f"• {k}: <b>{v}</b>")
    else:
        lines.append("• none")
    lines+=["","<b>After-Astra rejections:</b>"]
    if s["execution_rejections"]:
        for k,v in list(s["execution_rejections"].items())[:8]:
            lines.append(f"• {k}: <b>{v}</b>")
    else:
        lines.append("• none")
    return "\n".join(lines)

if __name__=="__main__":
    print(json.dumps(summary(),ensure_ascii=False,indent=2))

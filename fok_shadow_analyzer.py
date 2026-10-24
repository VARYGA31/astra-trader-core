#!/usr/bin/env python3
"""ASTRA FOK Shadow Analyzer.

Passive research only:
- observes ENTRY_FOK_NOT_FILLED decisions after the live execution path rejects them;
- assumes a hypothetical entry at the recorded executable touch;
- measures subsequent 1m market path at fixed horizons;
- never submits, cancels, amends or closes an order;
- never calls a model and never changes risk/execution settings.
"""
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import config
import market_snapshot
from asset_map import ASSETS

ORDER_CAPABILITY=False
MODEL_CAPABILITY=False
RISK_AUTHORITY=False
EXECUTION_AUTHORITY=False

DIR=Path(config.STATE_DIR)
CANDIDATES=DIR/"fok_shadow_candidates.jsonl"
OUTCOMES=DIR/"fok_shadow_outcomes.jsonl"


def _now():
    return datetime.now(timezone.utc)


def _parse_ts(x):
    try:
        return datetime.fromisoformat(str(x or "").replace("Z","+00:00"))
    except Exception:
        return None


def _num(x):
    try:
        y=float(x)
        return y if math.isfinite(y) else None
    except Exception:
        return None


def _read(path):
    out=[]
    try:
        with path.open("r",encoding="utf-8") as f:
            for line in f:
                try:
                    x=json.loads(line)
                    if isinstance(x,dict):
                        out.append(x)
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    return out


def _append(path,row):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("a",encoding="utf-8") as f:
        f.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")


def _id(parts):
    raw="|".join(str(x or "") for x in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def _reason(execution):
    return str((execution or {}).get("reason") or (execution or {}).get("status") or "").upper()


def record_rejection(package, decision, execution):
    """Persist one exact FOK miss for later outcome evaluation."""
    if not bool(config.FOK_SHADOW_ANALYZER_ENABLED):
        return {"status":"DISABLED"}
    if _reason(execution)!="ENTRY_FOK_NOT_FILLED":
        return {"status":"SKIPPED","reason":"NOT_FOK_MISS"}

    package=package or {}
    decision=decision or {}
    execution=execution or {}
    asset=str(decision.get("asset") or package.get("asset") or "").upper()
    side=str(decision.get("action") or "").upper()
    geometry=execution.get("shadow_risk_geometry") or {}
    entry=_num(execution.get("pre_order_reference"))
    if entry is None:
        entry=_num((execution.get("execution_quality") or {}).get("reference_price"))
    stop=_num(geometry.get("stop_loss"))
    tp1=_num(geometry.get("take_profit_1"))
    tp2=_num(geometry.get("take_profit_2"))
    if stop is None: stop=_num(decision.get("stop_loss"))
    if tp1 is None: tp1=_num(decision.get("take_profit_1"))
    if tp2 is None: tp2=_num(decision.get("take_profit_2"))

    if asset not in ASSETS or side not in {"LONG","SHORT"} or entry is None or entry<=0:
        return {"status":"SKIPPED","reason":"INCOMPLETE_FOK_EVIDENCE"}

    observed=_now().isoformat()
    attempts=execution.get("entry_attempts") or []
    order_id=execution.get("order_id") or ((attempts[-1] if attempts else {}) or {}).get("order_id")
    cid=_id([observed,asset,side,order_id,entry])
    row={
        "fok_shadow_version":1,
        "candidate_id":cid,
        "observed_at_utc":observed,
        "asset":asset,
        "side":side,
        "strategy_mode":str(decision.get("strategy_mode") or package.get("strategy_mode") or "NORMAL").upper(),
        "hypothetical_entry_price":entry,
        "hypothetical_entry_assumption":"PRE_ORDER_EXECUTABLE_TOUCH",
        "entry_limit_price":_num(execution.get("entry_limit_price")),
        "stop_loss":stop,
        "take_profit_1":tp1,
        "take_profit_2":tp2,
        "confidence":_num(decision.get("confidence")),
        "mtf_quality":_num(((decision.get("gate") or {}).get("mtf_quality"))),
        "setup_type":decision.get("setup_type"),
        "requested_qty_contracts":_num(execution.get("requested_qty_contracts")),
        "filled_qty_contracts":_num(execution.get("filled_qty_contracts")),
        "order_state":execution.get("order_state"),
        "entry_attempts":attempts,
    }
    _append(CANDIDATES,row)
    return {"status":"RECORDED","candidate_id":cid}


def _window_bars(candidate,bars,horizon_minutes):
    dt=_parse_ts(candidate.get("observed_at_utc"))
    if not dt:
        return []
    # Exclude the minute already in progress at observation time so high/low
    # cannot include price action that happened before the FOK rejection.
    start_ms=int(math.ceil(dt.timestamp()/60.0)*60*1000)
    end_ms=int((dt+timedelta(minutes=int(horizon_minutes))).timestamp()*1000)
    return [b for b in bars if start_ms<=int(b.get("open_time_ms") or 0)<end_ms]


def evaluate_candidate(candidate,bars,horizon_minutes):
    """Pure evaluator used by runtime and offline regression tests."""
    side=str(candidate.get("side") or "").upper()
    entry=_num(candidate.get("hypothetical_entry_price"))
    stop=_num(candidate.get("stop_loss"))
    tp1=_num(candidate.get("take_profit_1"))
    tp2=_num(candidate.get("take_profit_2"))
    window=_window_bars(candidate,bars,horizon_minutes)
    if side not in {"LONG","SHORT"} or entry is None or entry<=0 or not window:
        return None

    highs=[float(x["high"]) for x in window]
    lows=[float(x["low"]) for x in window]
    close=float(window[-1]["close"])
    risk=abs(entry-stop) if stop is not None else None

    if side=="LONG":
        signed_return=(close/entry-1.0)*100.0
        mfe=max(0.0,max(highs)-entry)
        mae=max(0.0,entry-min(lows))
    else:
        signed_return=(1.0-close/entry)*100.0
        mfe=max(0.0,entry-min(lows))
        mae=max(0.0,max(highs)-entry)

    path="TIME_EXIT"
    tp1_seen=False
    if stop is not None and tp1 is not None and tp2 is not None:
        for bar in window:
            hi=float(bar["high"]); lo=float(bar["low"])
            if side=="LONG":
                hit_stop=lo<=stop; hit1=hi>=tp1; hit2=hi>=tp2
            else:
                hit_stop=hi>=stop; hit1=lo<=tp1; hit2=lo<=tp2
            if hit_stop and (hit1 or hit2):
                path="AMBIGUOUS_SAME_BAR"
                break
            if hit2:
                path="TP2_HIT"
                tp1_seen=True
                break
            if hit1:
                tp1_seen=True
            if hit_stop:
                path="STOP_AFTER_TP1" if tp1_seen else "STOP_HIT"
                break
        else:
            if tp1_seen:
                path="TP1_TOUCHED_OPEN"

    time_exit_r=(signed_return/100.0*entry/risk) if risk and risk>0 else None
    return {
        "fok_shadow_version":1,
        "candidate_id":candidate.get("candidate_id"),
        "observed_at_utc":candidate.get("observed_at_utc"),
        "evaluated_at_utc":_now().isoformat(),
        "asset":candidate.get("asset"),
        "side":side,
        "strategy_mode":candidate.get("strategy_mode"),
        "horizon_minutes":int(horizon_minutes),
        "hypothetical_entry_price":entry,
        "evaluation_close":close,
        "signed_return_pct":round(signed_return,6),
        "positive":bool(signed_return>0),
        "mfe_pct":round(mfe/entry*100.0,6),
        "mae_pct":round(mae/entry*100.0,6),
        "mfe_r":round(mfe/risk,6) if risk and risk>0 else None,
        "mae_r":round(mae/risk,6) if risk and risk>0 else None,
        "time_exit_r":round(time_exit_r,6) if time_exit_r is not None else None,
        "path":path,
        "bar_count":len(window),
        "stop_loss":stop,
        "take_profit_1":tp1,
        "take_profit_2":tp2,
        "confidence":candidate.get("confidence"),
        "mtf_quality":candidate.get("mtf_quality"),
        "setup_type":candidate.get("setup_type"),
        "hypothetical_entry_assumption":candidate.get("hypothetical_entry_assumption"),
    }


def evaluate_due(batch=None):
    if not bool(config.FOK_SHADOW_ANALYZER_ENABLED):
        return {"status":"DISABLED","evaluated":0}
    candidates=_read(CANDIDATES)
    outcomes=_read(OUTCOMES)
    done={(x.get("candidate_id"),int(x.get("horizon_minutes") or 0)) for x in outcomes}
    utc=_now()
    pending=[]
    horizons=sorted(set(int(x) for x in config.FOK_SHADOW_HORIZONS_MINUTES if int(x)>0))
    for c in reversed(candidates):
        dt=_parse_ts(c.get("observed_at_utc"))
        if not dt: continue
        # OKX 1m replay request is intentionally capped at 300 completed bars.
        # Ignore evidence older than that instead of refetching it every worker tick.
        age_minutes=(utc-dt).total_seconds()/60.0
        if age_minutes>295.0:
            continue
        for h in horizons:
            key=(c.get("candidate_id"),h)
            if key in done: continue
            if utc>=dt+timedelta(minutes=h):
                pending.append((c,h))
                if len(pending)>=int(batch or config.FOK_SHADOW_MAX_PENDING):
                    break
        if len(pending)>=int(batch or config.FOK_SHADOW_MAX_PENDING):
            break
    if not pending:
        return {"status":"OK","evaluated":0}

    bars_cache={}
    added=0
    for c,h in reversed(pending):
        asset=str(c.get("asset") or "").upper()
        if asset not in ASSETS: continue
        if asset not in bars_cache:
            try:
                bars_cache[asset]=market_snapshot._okx_confirmed_candles(ASSETS[asset]["okx_swap"],"1m",300)
            except Exception:
                bars_cache[asset]=[]
        row=evaluate_candidate(c,bars_cache[asset],h)
        if row:
            _append(OUTCOMES,row)
            added+=1
    return {"status":"OK","evaluated":added}


def _stats(rows):
    usable=[x for x in rows if str(x.get("path"))!="AMBIGUOUS_SAME_BAR"]
    vals=[float(x.get("signed_return_pct") or 0) for x in usable]
    rvals=[float(x["time_exit_r"]) for x in usable if x.get("time_exit_r") is not None]
    mfe=[float(x["mfe_r"]) for x in usable if x.get("mfe_r") is not None]
    mae=[float(x["mae_r"]) for x in usable if x.get("mae_r") is not None]
    return {
        "samples":len(rows),
        "usable_samples":len(usable),
        "ambiguous":len(rows)-len(usable),
        "positive":sum(1 for x in usable if x.get("positive")),
        "hit_rate_pct":round(sum(1 for x in usable if x.get("positive"))/len(usable)*100.0,2) if usable else 0.0,
        "avg_signed_return_pct":round(statistics.mean(vals),6) if vals else None,
        "avg_time_exit_r":round(statistics.mean(rvals),4) if rvals else None,
        "avg_mfe_r":round(statistics.mean(mfe),4) if mfe else None,
        "avg_mae_r":round(statistics.mean(mae),4) if mae else None,
        "paths":dict(Counter(str(x.get("path") or "UNKNOWN") for x in rows)),
    }


def summary(hours=168):
    outcomes=_read(OUTCOMES)
    try:
        cutoff=_now()-timedelta(hours=float(hours))
        outcomes=[x for x in outcomes if (_parse_ts(x.get("observed_at_utc")) and _parse_ts(x.get("observed_at_utc"))>=cutoff)]
    except Exception:
        pass
    by_h=defaultdict(list)
    by_asset=defaultdict(list)
    for x in outcomes:
        by_h[str(int(x.get("horizon_minutes") or 0))].append(x)
        by_asset[str(x.get("asset") or "UNKNOWN")].append(x)
    return {
        "status":"OK" if config.FOK_SHADOW_ANALYZER_ENABLED else "DISABLED",
        "window_hours":float(hours),
        "candidates":len(_read(CANDIDATES)),
        "evaluated_rows":len(outcomes),
        "by_horizon":{k:_stats(v) for k,v in sorted(by_h.items(),key=lambda kv:int(kv[0]))},
        "by_asset":{k:_stats(v) for k,v in sorted(by_asset.items())},
        "recent":outcomes[-8:],
        "order_capability":False,
        "model_capability":False,
    }


if __name__=="__main__":
    print(json.dumps(summary(),ensure_ascii=False,indent=2))

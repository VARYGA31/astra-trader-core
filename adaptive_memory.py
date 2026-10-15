#!/usr/bin/env python3
"""ASTRA ADAPTIVE external memory and outcome evaluation.

This module never places orders and never calls OpenAI. It records every AUTO
cycle, evaluates what happened afterwards, and supplies similar past cases to
the strategist. The model weights are not modified; learning is external,
persistent and auditable under STATE_DIR.
"""
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import config
import market_snapshot
from asset_map import ASSETS

DIR = Path(config.STATE_DIR)
DECISIONS = DIR / "adaptive_decisions.jsonl"
OUTCOMES = DIR / "adaptive_outcomes.jsonl"
BRAIN = DIR / "adaptive_brain.json"

def now():
    return datetime.now(timezone.utc)

def now_iso():
    return now().isoformat()

def _parse_ts(x):
    try:
        return datetime.fromisoformat(str(x or "").replace("Z","+00:00"))
    except Exception:
        return None

def _atomic_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
    tmp.replace(path)

def _append(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a",encoding="utf-8") as f:
        f.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")
    _compact(path)

def _compact(path):
    try:
        cap=float(config.ADAPTIVE_LOG_MAX_MB)*1024*1024
        if cap<=0 or not path.exists() or path.stat().st_size<=cap:
            return
        target=int(cap*0.50)
        with path.open("rb") as f:
            f.seek(max(0,path.stat().st_size-target))
            chunk=f.read()
        nl=chunk.find(b"\n")
        if nl>=0:
            chunk=chunk[nl+1:]
        tmp=path.with_suffix(path.suffix+".compact.tmp")
        tmp.write_bytes(chunk)
        tmp.replace(path)
    except Exception:
        pass

def _read(path):
    out=[]
    try:
        with path.open("r",encoding="utf-8") as f:
            for line in f:
                try:
                    row=json.loads(line)
                    if isinstance(row,dict):
                        out.append(row)
                except Exception:
                    continue
    except Exception:
        pass
    return out

def _num(x):
    try:
        return float(x)
    except Exception:
        return None

def _frame_signature(tf):
    r=(tf or {}).get("regimes",{})
    ind=(tf or {}).get("indicators",{})
    vol=(tf or {}).get("volume",{})
    return {
        "trend":r.get("trend"),
        "structure":r.get("structure"),
        "momentum":r.get("momentum"),
        "rsi14":_num(ind.get("rsi14")),
        "atr_pct":_num(ind.get("atr_pct")),
        "volume_ratio":_num(vol.get("ratio_to_avg20")),
    }

def signature(package):
    market=(package or {}).get("decision_context",{}).get("market",{})
    frames=(market.get("multi_timeframe") or {}).get("frames",{})
    spot=market.get("spot") or {}
    perp=market.get("perp_okx") or {}
    return {
        "5m":_frame_signature(frames.get("5m")),
        "15m":_frame_signature(frames.get("15m")),
        "1h":_frame_signature(frames.get("1h")),
        "4h":_frame_signature(frames.get("4h")),
        "book_imbalance":_num((spot.get("order_book") or {}).get("imbalance")),
        "buy_sell_ratio":_num((spot.get("trade_flow") or {}).get("buy_sell_ratio")),
        "funding_rate":_num(perp.get("funding_rate")),
    }

def _reference_price(package):
    market=(package or {}).get("decision_context",{}).get("market",{})
    perp=market.get("perp_okx") or {}
    spot=market.get("spot") or {}
    return _num(perp.get("last_price")) or _num(spot.get("price"))

def save_brain(result):
    row=dict(result or {})
    row["saved_at_utc"]=now_iso()
    _atomic_json(BRAIN,row)
    return row

def load_brain():
    try:
        x=json.loads(BRAIN.read_text(encoding="utf-8"))
        return x if isinstance(x,dict) else {}
    except Exception:
        return {}

def record_cycle(result, packages):
    ts=str((result or {}).get("timestamp_utc") or now_iso())
    cycle_id=str((result or {}).get("cycle_id") or ts)
    best=(result or {}).get("best_opportunity") or {}
    best_asset=str(best.get("asset") or "").upper()
    opinions=(result or {}).get("assets") or []
    by_asset={str(x.get("asset") or "").upper():x for x in opinions if isinstance(x,dict)}
    rows=[]
    for asset,package in (packages or {}).items():
        opinion=by_asset.get(asset,{})
        is_best=(asset==best_asset and str(best.get("action") or "WAIT").upper() in {"LONG","SHORT"})
        row={
            "timestamp_utc":ts,
            "cycle_id":cycle_id,
            "asset":asset,
            "price":_reference_price(package),
            "score":opinion.get("score"),
            "bias":str(opinion.get("bias") or "NEUTRAL").upper(),
            "preferred_strategy":str(opinion.get("preferred_strategy") or "WAIT").upper(),
            "actionable":bool(opinion.get("actionable",False)),
            "confidence":opinion.get("confidence"),
            "reason":opinion.get("reason"),
            "signature":signature(package),
            "is_best":is_best,
            "best_action":str(best.get("action") or "WAIT").upper() if is_best else None,
            "best_strategy":str(best.get("strategy") or "").upper() if is_best else None,
            "entry":best.get("entry") if is_best else None,
            "stop_loss":best.get("stop_loss") if is_best else None,
            "take_profit_1":best.get("take_profit_1") if is_best else None,
            "take_profit_2":best.get("take_profit_2") if is_best else None,
            "time_horizon_minutes":best.get("time_horizon_minutes") if is_best else None,
        }
        if row["price"] is not None:
            _append(DECISIONS,row)
            rows.append(row)
    save_brain(result)
    return {"status":"OK","recorded":len(rows),"cycle_id":cycle_id}

def _directional_metrics(direction, price0, bars):
    price0=float(price0)
    direction=str(direction or "NEUTRAL").upper()
    if not bars or price0<=0:
        return None
    highs=[float(x["high"]) for x in bars]
    lows=[float(x["low"]) for x in bars]
    last=float(bars[-1]["close"])
    if direction=="LONG":
        final=(last/price0-1)*100
        mfe=(max(highs)/price0-1)*100
        mae=(min(lows)/price0-1)*100
    elif direction=="SHORT":
        final=(price0/last-1)*100
        mfe=(price0/min(lows)-1)*100
        mae=(price0/max(highs)-1)*100
    else:
        final=abs(last/price0-1)*100
        mfe=max(abs(max(highs)/price0-1),abs(min(lows)/price0-1))*100
        mae=0.0
    return {"final_directional_pct":final,"mfe_pct":mfe,"mae_pct":mae,"last_price":last}

def _trade_path(action, stop, tp1, tp2, bars):
    action=str(action or "").upper()
    try:
        stop=float(stop); tp1=float(tp1); tp2=float(tp2)
    except Exception:
        return None
    tp1_hit=False
    for bar in bars:
        hi=float(bar["high"]); lo=float(bar["low"])
        if action=="LONG":
            hit_stop=lo<=stop
            hit_tp1=hi>=tp1
            hit_tp2=hi>=tp2
        else:
            hit_stop=hi>=stop
            hit_tp1=lo<=tp1
            hit_tp2=lo<=tp2
        if hit_stop and (hit_tp1 or hit_tp2):
            return "AMBIGUOUS_BOTH_HIT"
        if hit_tp2:
            return "TP2_HIT"
        if hit_tp1:
            tp1_hit=True
        if hit_stop:
            return "STOP_AFTER_TP1" if tp1_hit else "STOP_HIT"
    return "TP1_ONLY" if tp1_hit else "OPEN_PATH"

def _threshold(strategy):
    return (
        float(config.ADAPTIVE_MISSED_MOVE_SCALP_PCT)
        if str(strategy or "").upper()=="SCALP"
        else float(config.ADAPTIVE_MISSED_MOVE_NORMAL_PCT)
    )

def _label_wait(row, metrics):
    bias=str(row.get("bias") or "NEUTRAL").upper()
    strategy=str(row.get("preferred_strategy") or "SCALP").upper()
    threshold=_threshold(strategy)
    if bias in {"LONG","SHORT"}:
        if metrics and metrics.get("mfe_pct",0)>=threshold:
            return "MISSED_MOVE"
        return "CORRECT_WAIT"
    if metrics and metrics.get("mfe_pct",0)>=threshold:
        return "WAIT_DURING_LARGE_MOVE"
    return "CORRECT_WAIT"

def evaluate_due(batch=None):
    decisions=_read(DECISIONS)
    outcomes=_read(OUTCOMES)
    done={(x.get("cycle_id"),x.get("asset"),int(x.get("horizon_minutes") or 0)) for x in outcomes}
    horizons=tuple(int(x) for x in config.ADAPTIVE_OUTCOME_HORIZONS_MINUTES)
    limit=int(batch or config.ADAPTIVE_OUTCOME_EVAL_BATCH)
    pending=[]
    utc=now()
    for row in reversed(decisions):
        dt=_parse_ts(row.get("timestamp_utc"))
        if not dt:
            continue
        for h in horizons:
            key=(row.get("cycle_id"),row.get("asset"),h)
            if key in done:
                continue
            if utc >= dt + timedelta(minutes=h):
                pending.append((row,h,dt))
                if len(pending)>=limit:
                    break
        if len(pending)>=limit:
            break
    if not pending:
        return {"status":"OK","evaluated":0}

    bars_cache={}
    added=0
    for row,h,dt in reversed(pending):
        asset=str(row.get("asset") or "").upper()
        if asset not in ASSETS:
            continue
        if asset not in bars_cache:
            try:
                bars_cache[asset]=market_snapshot._okx_confirmed_candles(ASSETS[asset]["okx_swap"],"5m",300)
            except Exception:
                bars_cache[asset]=[]
        start_ms=int(dt.timestamp()*1000)
        end_ms=int((dt+timedelta(minutes=h)).timestamp()*1000)
        bars=[x for x in bars_cache[asset] if start_ms<=int(x.get("open_time_ms",0))<=end_ms]
        if not bars:
            continue
        price0=_num(row.get("price"))
        if not price0:
            continue
        direction=str(row.get("best_action") or row.get("bias") or "NEUTRAL").upper()
        metrics=_directional_metrics(direction,price0,bars)
        if row.get("is_best") and direction in {"LONG","SHORT"}:
            label=_trade_path(direction,row.get("stop_loss"),row.get("take_profit_1"),row.get("take_profit_2"),bars) or "OPEN_PATH"
        else:
            label=_label_wait(row,metrics)
        out={
            "evaluated_at_utc":now_iso(),
            "timestamp_utc":row.get("timestamp_utc"),
            "cycle_id":row.get("cycle_id"),
            "asset":asset,
            "horizon_minutes":h,
            "score":row.get("score"),
            "bias":row.get("bias"),
            "strategy":row.get("best_strategy") or row.get("preferred_strategy"),
            "is_best":row.get("is_best"),
            "action":direction,
            "label":label,
            "metrics":metrics,
            "signature":row.get("signature"),
            "reason":row.get("reason"),
        }
        _append(OUTCOMES,out)
        done.add((row.get("cycle_id"),asset,h))
        added+=1
    return {"status":"OK","evaluated":added}

def _sig_similarity(a,b):
    score=0.0
    for tf in ("5m","15m","1h","4h"):
        aa=(a or {}).get(tf,{})
        bb=(b or {}).get(tf,{})
        for k in ("trend","structure","momentum"):
            if aa.get(k) and aa.get(k)==bb.get(k):
                score+=1.0
        ra=_num(aa.get("rsi14")); rb=_num(bb.get("rsi14"))
        if ra is not None and rb is not None:
            score+=max(0.0,1.0-abs(ra-rb)/30.0)
    return score

def similar_cases(packages, limit=None):
    outcomes=_read(OUTCOMES)
    limit=int(limit or config.ADAPTIVE_MEMORY_EXAMPLES)
    result={}
    for asset,package in (packages or {}).items():
        cur=signature(package)
        candidates=[]
        for row in outcomes:
            if str(row.get("asset") or "").upper()!=asset:
                continue
            candidates.append((_sig_similarity(cur,row.get("signature") or {}),row))
        candidates.sort(key=lambda x:x[0],reverse=True)
        result[asset]=[
            {
                "similarity":round(s,2),
                "horizon_minutes":r.get("horizon_minutes"),
                "bias":r.get("bias"),
                "strategy":r.get("strategy"),
                "action":r.get("action"),
                "label":r.get("label"),
                "metrics":r.get("metrics"),
            }
            for s,r in candidates[:max(1,limit//max(1,len(packages)))]
        ]
    return result

def summary(hours=168):
    cutoff=now()-timedelta(hours=float(hours))
    outcomes=[x for x in _read(OUTCOMES) if (_parse_ts(x.get("evaluated_at_utc")) or datetime.min.replace(tzinfo=timezone.utc))>=cutoff]
    decisions=[x for x in _read(DECISIONS) if (_parse_ts(x.get("timestamp_utc")) or datetime.min.replace(tzinfo=timezone.utc))>=cutoff]
    labels=Counter(str(x.get("label") or "UNKNOWN") for x in outcomes)
    by_asset=defaultdict(Counter)
    by_strategy=defaultdict(Counter)
    for x in outcomes:
        by_asset[str(x.get("asset") or "UNKNOWN")][str(x.get("label") or "UNKNOWN")]+=1
        by_strategy[str(x.get("strategy") or "UNKNOWN")][str(x.get("label") or "UNKNOWN")]+=1
    return {
        "hours":float(hours),
        "decisions":len(decisions),
        "evaluated_outcomes":len(outcomes),
        "labels":dict(labels),
        "by_asset":{k:dict(v) for k,v in by_asset.items()},
        "by_strategy":{k:dict(v) for k,v in by_strategy.items()},
    }

def brain_text():
    b=load_brain()
    if not b:
        return "🧠 <b>ASTRA BRAIN</b>\n\nПока нет AUTO-анализа."
    lines=["🧠 <b>ASTRA BRAIN</b>","",str(b.get("market_summary") or "")]
    for x in b.get("assets") or []:
        lines.append(
            f"\n<b>{x.get('asset')}</b> — {x.get('score','—')}/100 | "
            f"{x.get('bias','NEUTRAL')} | {x.get('preferred_strategy','WAIT')}"
        )
        if x.get("reason"):
            lines.append(str(x.get("reason")))
    best=b.get("best_opportunity") or {}
    lines += ["","<b>Best opportunity:</b>"]
    if str(best.get("action") or "WAIT").upper()=="WAIT":
        lines.append("WAIT — "+str(best.get("reason") or b.get("reason") or "нет качественного входа"))
    else:
        lines.append(
            f"{best.get('asset')} {best.get('action')} {best.get('strategy')} | "
            f"confidence {best.get('confidence','—')} | quality {best.get('setup_quality','—')}"
        )
        lines.append(str(best.get("reason") or ""))
    return "\n".join(lines)

def learning_text(hours=168):
    s=summary(hours)
    labels=s.get("labels",{})
    lines=[
        f"🎓 <b>ASTRA LEARNING — {int(float(hours))}h</b>",
        "",
        f"Наблюдений: <b>{s.get('decisions',0)}</b>",
        f"Оценённых исходов: <b>{s.get('evaluated_outcomes',0)}</b>",
        f"Correct WAIT: <b>{labels.get('CORRECT_WAIT',0)}</b>",
        f"Missed move: <b>{labels.get('MISSED_MOVE',0)}</b>",
        f"WAIT during large move: <b>{labels.get('WAIT_DURING_LARGE_MOVE',0)}</b>",
        f"TP2 hit: <b>{labels.get('TP2_HIT',0)}</b>",
        f"TP1 only: <b>{labels.get('TP1_ONLY',0)}</b>",
        f"Stop hit: <b>{labels.get('STOP_HIT',0)}</b>",
        "",
        "Это внешняя память решений, а не переобучение весов модели.",
    ]
    return "\n".join(lines)

#!/usr/bin/env python3
"""Cost controls and local opportunity scan for ASTRA ADAPTIVE.

The local scan is intentionally NOT a trading gate. Its only purpose is to
decide whether spending a GPT-6 Astra call before the normal baseline interval
is justified. Final trade decisions still come from ASTRA + deterministic
Safety/Risk/Execution.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import config

USAGE_FILE=Path(config.STATE_DIR)/"openai_usage.jsonl"

def now():
    return datetime.now(timezone.utc)

def _parse_ts(x):
    try:
        return datetime.fromisoformat(str(x or "").replace("Z","+00:00"))
    except Exception:
        return None

def _num(x):
    try:
        return float(x)
    except Exception:
        return None

def _rows():
    out=[]
    try:
        with USAGE_FILE.open("r",encoding="utf-8") as f:
            for line in f:
                try:
                    x=json.loads(line)
                    if isinstance(x,dict):
                        out.append(x)
                except Exception:
                    continue
    except Exception:
        pass
    return out

def usage_today():
    d=now().date()
    calls=0
    input_tokens=0
    cached_input_tokens=0
    output_tokens=0
    total_tokens=0
    by_model={}
    for x in _rows():
        ts=_parse_ts(x.get("timestamp_utc"))
        if not ts or ts.date()!=d:
            continue
        if str(x.get("strategy_mode") or "").upper()!="AUTO":
            continue
        calls+=1
        i=int(x.get("input_tokens") or 0)
        ci=int(x.get("cached_input_tokens") or 0)
        o=int(x.get("output_tokens") or 0)
        t=int(x.get("total_tokens") or (i+o))
        input_tokens+=i
        cached_input_tokens+=ci
        output_tokens+=o
        total_tokens+=t
        model=str(x.get("model") or "UNKNOWN")
        by_model[model]=by_model.get(model,0)+1

    uncached=max(0,input_tokens-cached_input_tokens)
    cost=(
        uncached*float(config.ADAPTIVE_PRICE_INPUT_USD_PER_M)
        + cached_input_tokens*float(config.ADAPTIVE_PRICE_CACHED_INPUT_USD_PER_M)
        + output_tokens*float(config.ADAPTIVE_PRICE_OUTPUT_USD_PER_M)
    )/1_000_000.0

    max_calls=max(1,int(config.ADAPTIVE_MAX_MODEL_CALLS_PER_DAY))
    max_usd=max(0.0,float(config.ADAPTIVE_MAX_ESTIMATED_USD_PER_DAY))
    call_remaining=max(0,max_calls-calls)
    usd_remaining=max(0.0,max_usd-cost) if max_usd>0 else None
    return {
        "date_utc":str(d),
        "calls":calls,
        "max_calls":max_calls,
        "calls_remaining":call_remaining,
        "input_tokens":input_tokens,
        "cached_input_tokens":cached_input_tokens,
        "output_tokens":output_tokens,
        "total_tokens":total_tokens,
        "estimated_cost_usd":round(cost,4),
        "max_estimated_cost_usd":max_usd if max_usd>0 else None,
        "estimated_cost_remaining_usd":round(usd_remaining,4) if usd_remaining is not None else None,
        "by_model":by_model,
    }

def budget_status():
    u=usage_today()
    if u["calls"]>=u["max_calls"]:
        return {"allowed":False,"reason":"DAILY_MODEL_CALL_CAP","usage":u}
    cap=u.get("max_estimated_cost_usd")
    if cap is not None and float(u.get("estimated_cost_usd") or 0)>=float(cap):
        return {"allowed":False,"reason":"DAILY_ESTIMATED_COST_CAP","usage":u}
    return {"allowed":True,"reason":"OK","usage":u}

def reserve_status():
    """Protect some daily budget for strong late-day opportunities/news."""
    u=usage_today()
    reserve_calls=max(0,int(config.ADAPTIVE_BASELINE_RESERVE_CALLS))
    reserve_usd=max(0.0,float(config.ADAPTIVE_BASELINE_RESERVE_USD))
    next_call=max(0.0,float(config.ADAPTIVE_ESTIMATED_NEXT_CALL_USD))
    calls_ok=int(u.get("calls_remaining") or 0)>reserve_calls
    usd_left=u.get("estimated_cost_remaining_usd")
    usd_ok=True if usd_left is None else float(usd_left)>=(reserve_usd+next_call)
    return {
        "baseline_allowed":bool(calls_ok and usd_ok),
        "reserve_calls":reserve_calls,
        "reserve_usd":reserve_usd,
        "estimated_next_call_usd":next_call,
        "calls_remaining":u.get("calls_remaining"),
        "estimated_cost_remaining_usd":usd_left,
    }

def _spread_pct(package):
    perp=(package or {}).get("decision_context",{}).get("market",{}).get("perp_okx",{})
    bid=_num(perp.get("bid_price")); ask=_num(perp.get("ask_price"))
    if bid is None or ask is None or bid<=0 or ask<bid:
        return None
    mid=(bid+ask)/2
    return ((ask-bid)/mid*100) if mid else None

def _frame(package,tf):
    return (
        (package or {}).get("decision_context",{})
        .get("market",{})
        .get("multi_timeframe",{})
        .get("frames",{})
        .get(tf,{})
    )

def _direction_score(package,direction):
    """Cheap score for deciding whether an EARLY model call is worth paying for."""
    direction=str(direction).upper()
    score=0.0
    reasons=[]
    f5=_frame(package,"5m")
    f15=_frame(package,"15m")
    f1h=_frame(package,"1h")

    def match(frame,key,bull,bear):
        v=(frame.get("regimes") or {}).get(key)
        return v==(bull if direction=="LONG" else bear)

    if match(f1h,"trend","BULLISH","BEARISH"):
        score+=1.3; reasons.append("1H_TREND")
    if match(f1h,"structure","BULLISH","BEARISH"):
        score+=1.0; reasons.append("1H_STRUCTURE")
    if match(f15,"momentum","BULLISH","BEARISH"):
        score+=1.0; reasons.append("15M_MOMENTUM")
    if match(f15,"structure","BULLISH","BEARISH"):
        score+=0.8; reasons.append("15M_STRUCTURE")
    if match(f5,"momentum","BULLISH","BEARISH"):
        score+=0.9; reasons.append("5M_MOMENTUM")
    if match(f5,"structure","BULLISH","BEARISH"):
        score+=0.7; reasons.append("5M_STRUCTURE")

    st=f5.get("structure") or {}
    if (direction=="LONG" and st.get("breakout_up")) or (direction=="SHORT" and st.get("breakout_down")):
        score+=1.4; reasons.append("5M_BREAKOUT")

    vol=_num((f5.get("volume") or {}).get("ratio_to_avg20"))
    if vol is not None:
        if vol>=1.5:
            score+=1.2; reasons.append("VOLUME_1_5X")
        elif vol>=1.0:
            score+=0.6; reasons.append("VOLUME_1X")

    ch=_num((f5.get("changes_pct") or {}).get("1bar"))
    if ch is not None:
        if direction=="LONG" and ch>=float(config.ADAPTIVE_TRIGGER_5M_MOVE_PCT):
            score+=0.7; reasons.append("5M_MOVE")
        if direction=="SHORT" and ch<=-float(config.ADAPTIVE_TRIGGER_5M_MOVE_PCT):
            score+=0.7; reasons.append("5M_MOVE")

    spread=_spread_pct(package)
    if spread is None:
        score-=0.5
    elif spread<=float(config.ADAPTIVE_TRIGGER_MAX_SPREAD_PCT):
        score+=0.5; reasons.append("TIGHT_SPREAD")
    else:
        score-=1.0

    g=(package or {}).get("guards",{})
    if g.get("market_stale") or not g.get("market_ok",False) or not g.get("news_ok",False):
        score-=3.0
    if not g.get("critical_news_verified",False):
        score-=2.0

    return {"score":round(score,2),"reasons":reasons,"spread_pct":spread}

def local_scan(packages):
    assets={}
    best={"asset":None,"direction":None,"score":-999.0,"reasons":[]}
    for asset,p in (packages or {}).items():
        long=_direction_score(p,"LONG")
        short=_direction_score(p,"SHORT")
        pick=("LONG",long) if long["score"]>=short["score"] else ("SHORT",short)
        assets[asset]={
            "long_score":long["score"],
            "short_score":short["score"],
            "best_direction":pick[0],
            "best_score":pick[1]["score"],
            "reasons":pick[1]["reasons"],
            "spread_pct":pick[1]["spread_pct"],
        }
        if pick[1]["score"]>best["score"]:
            best={
                "asset":asset,
                "direction":pick[0],
                "score":pick[1]["score"],
                "reasons":pick[1]["reasons"],
            }
    return {
        "threshold":float(config.ADAPTIVE_TRIGGER_SCORE),
        "triggered":bool(best["score"]>=float(config.ADAPTIVE_TRIGGER_SCORE)),
        "best":best,
        "assets":assets,
    }

def seconds_since(ts):
    dt=_parse_ts(ts)
    if not dt:
        return 10**9
    return max(0.0,(now()-dt).total_seconds())

def plan(packages,state,force=False):
    budget=budget_status()
    scan=local_scan(packages)
    if not budget["allowed"]:
        return {
            "call_model":False,
            "reason":budget["reason"],
            "budget":budget,
            "local_scan":scan,
        }

    elapsed=seconds_since((state or {}).get("last_model_call_at_utc"))
    base=float(config.ADAPTIVE_BASE_MODEL_INTERVAL_MINUTES)*60
    fast=float(config.ADAPTIVE_TRIGGER_MIN_GAP_MINUTES)*60
    reserve=reserve_status()

    if force and elapsed>=fast:
        return {"call_model":True,"reason":"VERIFIED_EVENT","budget":budget,"reserve":reserve,"local_scan":scan}
    if elapsed>=base and reserve.get("baseline_allowed"):
        return {"call_model":True,"reason":"BASELINE_INTERVAL","budget":budget,"reserve":reserve,"local_scan":scan}
    if scan.get("triggered") and elapsed>=fast:
        return {"call_model":True,"reason":"LOCAL_OPPORTUNITY_TRIGGER","budget":budget,"reserve":reserve,"local_scan":scan}
    if elapsed>=base and not reserve.get("baseline_allowed"):
        return {
            "call_model":False,
            "reason":"BASELINE_RESERVE_PROTECTED",
            "budget":budget,
            "reserve":reserve,
            "local_scan":scan,
        }

    return {
        "call_model":False,
        "reason":"COST_SMART_WAIT",
        "seconds_until_baseline":max(0,int(base-elapsed)),
        "seconds_until_trigger_allowed":max(0,int(fast-elapsed)),
        "budget":budget,
        "reserve":reserve,
        "local_scan":scan,
    }

def telegram_text():
    u=usage_today()
    lines=[
        "💰 <b>ASTRA AUTO COST</b>",
        "",
        f"UTC date: <b>{u['date_utc']}</b>",
        f"AUTO model calls: <b>{u['calls']} / {u['max_calls']}</b>",
        f"Input tokens: <b>{u['input_tokens']:,}</b>",
        f"Cached input: <b>{u['cached_input_tokens']:,}</b>",
        f"Output tokens: <b>{u['output_tokens']:,}</b>",
        f"Estimated AUTO cost: <b>USD {u['estimated_cost_usd']:.2f}</b>",
        (
            f"Daily estimated cap: <b>USD {u['max_estimated_cost_usd']:.2f}</b>"
            if u.get("max_estimated_cost_usd") is not None else
            "Daily estimated cap: <b>OFF</b>"
        ),
        "",
    ]
    if config.ADAPTIVE_TRAINER_V2_ENABLED:
        lines += [
            "Mode: <b>TRAINER v2 event-driven</b>",
            f"Model min gap: <b>{config.ADAPTIVE_TRAINER_MODEL_MIN_GAP_MINUTES} min</b>",
            f"Candidate threshold: <b>{config.ADAPTIVE_TRAINER_MIN_MODEL_QUALITY:.0f}/100</b>",
            "Нет фоновых baseline-вызовов Astra.",
            "Каждая 5m свеча тренируется/оценивается локально без OpenAI API.",
            "Astra вызывается только для готового кандидата.",
        ]
    else:
        lines += [
            f"Baseline Astra interval: <b>{config.ADAPTIVE_BASE_MODEL_INTERVAL_MINUTES} min</b>",
            f"Early-trigger min gap: <b>{config.ADAPTIVE_TRIGGER_MIN_GAP_MINUTES} min</b>",
            f"Protected reserve: <b>{config.ADAPTIVE_BASELINE_RESERVE_CALLS} calls / USD {config.ADAPTIVE_BASELINE_RESERVE_USD:.2f}</b>",
            "Локальный 5m-скан между вызовами модели не расходует OpenAI API.",
        ]
    return "\n".join(lines)

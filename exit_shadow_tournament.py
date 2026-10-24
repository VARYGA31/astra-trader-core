#!/usr/bin/env python3
"""ASTRA Exit Shadow Tournament.

Replays each real OKX demo entry through deterministic hypothetical exit policies.
This module is research-only: it never places/closes/amends orders and never changes
live stop/TP logic. Evaluation uses only completed 1m candles after the entry.
"""
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
TRADE_JOURNAL=DIR/"trade_journal.jsonl"
OUTCOMES=DIR/"exit_shadow_tournament.jsonl"


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
                    if isinstance(x,dict): out.append(x)
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    return out


def _append(path,row):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("a",encoding="utf-8") as f:
        f.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")


def _open_id(e):
    return str(e.get("order_id") or f"{e.get('asset')}|{e.get('opened_at_utc')}|{e.get('entry')}")


def _window_bars(open_event,bars,horizon_minutes):
    dt=_parse_ts(open_event.get("opened_at_utc"))
    if not dt: return []
    start_ms=int(math.ceil(dt.timestamp()/60.0)*60*1000)
    end_ms=int((dt+timedelta(minutes=int(horizon_minutes))).timestamp()*1000)
    return [b for b in bars if start_ms<=int(b.get("open_time_ms") or 0)<end_ms]


def _signed_r(side,entry,price,risk):
    if not risk or risk<=0: return None
    pnl=(float(price)-entry) if side=="LONG" else (entry-float(price))
    return pnl/risk


def _hit(side,bar,level,kind):
    if level is None: return False
    hi=float(bar["high"]); lo=float(bar["low"]); level=float(level)
    if side=="LONG":
        return lo<=level if kind=="STOP" else hi>=level
    return hi>=level if kind=="STOP" else lo<=level


def _full_target(side,entry,stop,target,bars,name):
    risk=abs(entry-stop)
    target_r=abs(target-entry)/risk if risk>0 else None
    for b in bars:
        hs=_hit(side,b,stop,"STOP")
        ht=_hit(side,b,target,"TARGET")
        if hs and ht:
            return {"policy":name,"status":"AMBIGUOUS","gross_r":None,"exit_reason":"STOP_AND_TARGET_SAME_BAR"}
        if ht:
            return {"policy":name,"status":"OK","gross_r":target_r,"exit_reason":"TARGET"}
        if hs:
            return {"policy":name,"status":"OK","gross_r":-1.0,"exit_reason":"STOP"}
    r=_signed_r(side,entry,bars[-1]["close"],risk)
    return {"policy":name,"status":"OK","gross_r":r,"exit_reason":"TIME_EXIT"}


def _partial_runner(side,entry,stop,tp1,tp2,bars,first_fraction,name):
    risk=abs(entry-stop)
    tp1_r=abs(tp1-entry)/risk
    tp2_r=abs(tp2-entry)/risk
    runner=1.0-float(first_fraction)
    first_done=False
    realized=0.0

    for b in bars:
        if not first_done:
            hs=_hit(side,b,stop,"STOP")
            h1=_hit(side,b,tp1,"TARGET")
            h2=_hit(side,b,tp2,"TARGET")
            if hs and (h1 or h2):
                return {"policy":name,"status":"AMBIGUOUS","gross_r":None,"exit_reason":"STOP_AND_TARGET_SAME_BAR"}
            if h2:
                # Crossing TP2 necessarily crosses TP1 in the same direction.
                return {"policy":name,"status":"OK","gross_r":first_fraction*tp1_r+runner*tp2_r,"exit_reason":"TP1_THEN_TP2"}
            if h1:
                first_done=True
                realized=first_fraction*tp1_r
                # Runner becomes active from the next complete minute. This avoids
                # inventing intrabar ordering inside the TP1 candle.
                continue
            if hs:
                return {"policy":name,"status":"OK","gross_r":-1.0,"exit_reason":"STOP"}
        else:
            hbe=_hit(side,b,entry,"STOP")
            h2=_hit(side,b,tp2,"TARGET")
            if hbe and h2:
                return {"policy":name,"status":"AMBIGUOUS","gross_r":None,"exit_reason":"BE_AND_TP2_SAME_BAR"}
            if h2:
                return {"policy":name,"status":"OK","gross_r":realized+runner*tp2_r,"exit_reason":"TP1_THEN_TP2"}
            if hbe:
                return {"policy":name,"status":"OK","gross_r":realized,"exit_reason":"TP1_THEN_BE"}

    last_r=_signed_r(side,entry,bars[-1]["close"],risk)
    if first_done:
        return {"policy":name,"status":"OK","gross_r":realized+runner*last_r,"exit_reason":"TP1_THEN_TIME"}
    return {"policy":name,"status":"OK","gross_r":last_r,"exit_reason":"TIME_EXIT"}


def _trail_after_tp1(side,entry,stop,tp1,bars):
    """50% at TP1, runner trails by one initial R using prior completed bars."""
    risk=abs(entry-stop)
    tp1_r=abs(tp1-entry)/risk
    first_done=False
    realized=0.0
    favorable_extreme=entry
    trail=entry

    for b in bars:
        if not first_done:
            hs=_hit(side,b,stop,"STOP")
            h1=_hit(side,b,tp1,"TARGET")
            if hs and h1:
                return {"policy":"TRAIL_AFTER_TP1","status":"AMBIGUOUS","gross_r":None,"exit_reason":"STOP_AND_TP1_SAME_BAR"}
            if h1:
                first_done=True
                realized=0.5*tp1_r
                favorable_extreme=tp1
                trail=entry
                continue
            if hs:
                return {"policy":"TRAIL_AFTER_TP1","status":"OK","gross_r":-1.0,"exit_reason":"STOP"}
        else:
            # Test the trail computed only from prior completed bars.
            if _hit(side,b,trail,"STOP"):
                runner_r=_signed_r(side,entry,trail,risk)
                return {
                    "policy":"TRAIL_AFTER_TP1","status":"OK",
                    "gross_r":realized+0.5*runner_r,
                    "exit_reason":"TP1_THEN_TRAIL",
                }
            if side=="LONG":
                favorable_extreme=max(favorable_extreme,float(b["high"]))
                trail=max(entry,favorable_extreme-risk)
            else:
                favorable_extreme=min(favorable_extreme,float(b["low"]))
                trail=min(entry,favorable_extreme+risk)

    last_r=_signed_r(side,entry,bars[-1]["close"],risk)
    if first_done:
        return {
            "policy":"TRAIL_AFTER_TP1","status":"OK",
            "gross_r":realized+0.5*last_r,
            "exit_reason":"TP1_THEN_TIME",
        }
    return {"policy":"TRAIL_AFTER_TP1","status":"OK","gross_r":last_r,"exit_reason":"TIME_EXIT"}


def simulate(open_event,bars,horizon_minutes=None):
    """Pure tournament simulation for one real entry."""
    horizon=int(horizon_minutes or config.EXIT_SHADOW_HORIZON_MINUTES)
    side=str(open_event.get("side") or "").upper()
    entry=_num(open_event.get("entry"))
    stop=_num(open_event.get("stop_loss"))
    tp1=_num(open_event.get("take_profit_1"))
    tp2=_num(open_event.get("take_profit_2"))
    window=_window_bars(open_event,bars,horizon)
    if side not in {"LONG","SHORT"} or None in (entry,stop,tp1,tp2) or not window:
        return None
    risk=abs(entry-stop)
    if risk<=0:
        return None

    policies=[
        _full_target(side,entry,stop,tp1,window,"TP1_FULL"),
        _full_target(side,entry,stop,tp2,window,"TP2_FULL"),
        _partial_runner(side,entry,stop,tp1,tp2,window,0.80,"80_20_BE_RUNNER"),
        _partial_runner(side,entry,stop,tp1,tp2,window,0.50,"50_50_BE_RUNNER"),
        _trail_after_tp1(side,entry,stop,tp1,window),
    ]

    # Same conservative friction for all policies. Partial exits do not get a
    # free advantage: their total exited notional still sums to one position.
    try:
        cost_pct=2.0*(
            float(config.TRAINER_TAKER_FEE_PCT_PER_SIDE)
            +float(config.TRAINER_SLIPPAGE_PCT_PER_SIDE)
        )
        risk_pct=risk/entry*100.0
        cost_r=cost_pct/risk_pct if risk_pct>0 else 0.0
    except Exception:
        cost_r=0.0

    for p in policies:
        p["estimated_cost_r"]=round(cost_r,6)
        p["estimated_net_r"]=(
            round(float(p["gross_r"])-cost_r,6)
            if p.get("gross_r") is not None and p.get("status")=="OK"
            else None
        )

    return {
        "exit_shadow_version":1,
        "open_id":_open_id(open_event),
        "asset":open_event.get("asset"),
        "side":side,
        "strategy_mode":open_event.get("strategy_mode") or "NORMAL",
        "opened_at_utc":open_event.get("opened_at_utc"),
        "evaluated_at_utc":_now().isoformat(),
        "horizon_minutes":horizon,
        "entry":entry,
        "stop_loss":stop,
        "take_profit_1":tp1,
        "take_profit_2":tp2,
        "initial_risk_distance":risk,
        "bar_count":len(window),
        "policies":policies,
    }


def evaluate_due(batch=None):
    if not bool(config.EXIT_SHADOW_TOURNAMENT_ENABLED):
        return {"status":"DISABLED","evaluated":0}
    events=_read(TRADE_JOURNAL)
    opens=[x for x in events if x.get("event")=="OKX_POSITION_OPENED"]
    outcomes=_read(OUTCOMES)
    done={str(x.get("open_id")) for x in outcomes}
    horizon=int(config.EXIT_SHADOW_HORIZON_MINUTES)
    utc=_now()
    pending=[]
    for e in reversed(opens):
        oid=_open_id(e)
        if oid in done: continue
        dt=_parse_ts(e.get("opened_at_utc"))
        if not dt: continue
        if utc>=dt+timedelta(minutes=horizon):
            pending.append(e)
            if len(pending)>=int(batch or config.EXIT_SHADOW_MAX_PENDING): break
    if not pending:
        return {"status":"OK","evaluated":0}

    bars_cache={}
    added=0
    for e in reversed(pending):
        asset=str(e.get("asset") or "").upper()
        if asset not in ASSETS: continue
        if asset not in bars_cache:
            try:
                bars_cache[asset]=market_snapshot._okx_confirmed_candles(ASSETS[asset]["okx_swap"],"1m",300)
            except Exception:
                bars_cache[asset]=[]
        row=simulate(e,bars_cache[asset],horizon)
        if row:
            _append(OUTCOMES,row)
            added+=1
    return {"status":"OK","evaluated":added}


def _policy_stats(rows):
    usable=[x for x in rows if x.get("status")=="OK" and x.get("estimated_net_r") is not None]
    vals=[float(x["estimated_net_r"]) for x in usable]
    gross=[float(x["gross_r"]) for x in usable if x.get("gross_r") is not None]
    wins=[x for x in usable if float(x["estimated_net_r"])>0]
    losses=[x for x in usable if float(x["estimated_net_r"])<0]
    pos=sum(float(x["estimated_net_r"]) for x in wins)
    neg=abs(sum(float(x["estimated_net_r"]) for x in losses))
    return {
        "samples":len(rows),
        "usable_samples":len(usable),
        "ambiguous":len(rows)-len(usable),
        "wins":len(wins),
        "losses":len(losses),
        "win_rate_pct":round(len(wins)/len(usable)*100.0,2) if usable else 0.0,
        "avg_gross_r":round(statistics.mean(gross),4) if gross else None,
        "avg_net_r":round(statistics.mean(vals),4) if vals else None,
        "profit_factor_r":round(pos/neg,3) if neg>0 else (999.0 if pos>0 else 0.0),
        "exit_reasons":dict(Counter(str(x.get("exit_reason") or "UNKNOWN") for x in rows)),
    }


def summary(hours=168):
    outcomes=_read(OUTCOMES)
    try:
        cutoff=_now()-timedelta(hours=float(hours))
        outcomes=[x for x in outcomes if (_parse_ts(x.get("opened_at_utc")) and _parse_ts(x.get("opened_at_utc"))>=cutoff)]
    except Exception:
        pass

    by_policy=defaultdict(list)
    by_asset=defaultdict(lambda:defaultdict(list))
    for row in outcomes:
        for p in row.get("policies") or []:
            name=str(p.get("policy") or "UNKNOWN")
            by_policy[name].append(p)
            by_asset[str(row.get("asset") or "UNKNOWN")][name].append(p)

    leaderboard=[]
    for name,rows in by_policy.items():
        s=_policy_stats(rows)
        leaderboard.append({"policy":name,**s})
    leaderboard.sort(key=lambda x:(
        -(x.get("avg_net_r") if x.get("avg_net_r") is not None else -999),
        -x.get("usable_samples",0),
    ))

    return {
        "status":"OK" if config.EXIT_SHADOW_TOURNAMENT_ENABLED else "DISABLED",
        "window_hours":float(hours),
        "horizon_minutes":int(config.EXIT_SHADOW_HORIZON_MINUTES),
        "evaluated_trades":len(outcomes),
        "leaderboard":leaderboard,
        "by_asset":{
            asset:{name:_policy_stats(rows) for name,rows in sorted(policies.items())}
            for asset,policies in sorted(by_asset.items())
        },
        "recent":outcomes[-5:],
        "order_capability":False,
        "model_capability":False,
    }


if __name__=="__main__":
    print(json.dumps(summary(),ensure_ascii=False,indent=2))

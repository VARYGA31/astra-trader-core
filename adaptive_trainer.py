#!/usr/bin/env python3
"""ASTRA Trainer v2: zero-token shadow practice + empirical online learning.

The trainer never places orders and never calls OpenAI. On every new confirmed
5m candle it builds risk-aligned hypothetical NORMAL/SCALP candidates, records
them, evaluates their later outcome from OKX candles, and uses those outcomes
to adjust future candidate ranking conservatively.

This is real external online learning, not neural-weight retraining.
"""
import json, math, hashlib
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import config
import market_snapshot
import decision_gate, scalp_gate
from asset_map import ASSETS

DIR=Path(config.STATE_DIR)
CANDIDATES=DIR/"adaptive_trainer_candidates.jsonl"
OUTCOMES=DIR/"adaptive_trainer_outcomes.jsonl"

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

def _clamp(x,lo,hi):
    try: return max(lo,min(hi,float(x)))
    except Exception: return lo

def _append(path,row):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("a",encoding="utf-8") as f:
        f.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")
    _compact(path)

def _compact(path):
    try:
        cap=float(config.ADAPTIVE_TRAINER_LOG_MAX_MB)*1024*1024
        if cap<=0 or not path.exists() or path.stat().st_size<=cap:
            return
        target=int(cap*0.55)
        with path.open("rb") as f:
            f.seek(max(0,path.stat().st_size-target))
            chunk=f.read()
        i=chunk.find(b"\n")
        if i>=0: chunk=chunk[i+1:]
        tmp=path.with_suffix(path.suffix+".tmp")
        tmp.write_bytes(chunk); tmp.replace(path)
    except Exception:
        pass

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
    except Exception:
        pass
    return out

def _frame(package,tf):
    return (
        (package or {}).get("decision_context",{})
        .get("market",{}).get("multi_timeframe",{})
        .get("frames",{}).get(tf,{})
    )

def _regime(tf,key):
    return (tf.get("regimes") or {}).get(key)

def _match(tf,key,direction):
    wanted="BULLISH" if direction=="LONG" else "BEARISH"
    return _regime(tf,key)==wanted

def _oppose(tf,key,direction):
    wanted="BEARISH" if direction=="LONG" else "BULLISH"
    return _regime(tf,key)==wanted

def _spread_pct(package):
    p=(package or {}).get("decision_context",{}).get("market",{}).get("perp_okx",{})
    bid=_num(p.get("bid_price")); ask=_num(p.get("ask_price"))
    if bid is None or ask is None or bid<=0 or ask<bid:
        return None
    mid=(bid+ask)/2
    return (ask-bid)/mid*100 if mid else None

def _entry(package):
    m=(package or {}).get("decision_context",{}).get("market",{})
    return _num((m.get("perp_okx") or {}).get("last_price")) or _num((m.get("spot") or {}).get("price"))

def _tags(package,direction,strategy):
    tags=[str(strategy),str(direction)]
    for tf in ("5m","15m","1h","4h"):
        x=_frame(package,tf)
        if _match(x,"trend",direction): tags.append(tf.upper()+"_TREND_MATCH")
        if _match(x,"structure",direction): tags.append(tf.upper()+"_STRUCT_MATCH")
        if _match(x,"momentum",direction): tags.append(tf.upper()+"_MOM_MATCH")
    f5=_frame(package,"5m")
    st=f5.get("structure") or {}
    if direction=="LONG" and st.get("breakout_up"): tags.append("BREAKOUT")
    if direction=="SHORT" and st.get("breakout_down"): tags.append("BREAKOUT")
    vr=_num((f5.get("volume") or {}).get("ratio_to_avg20"))
    if vr is not None:
        tags.append("VOL_HIGH" if vr>=1.5 else "VOL_OK" if vr>=0.9 else "VOL_LOW")
    sp=_spread_pct(package)
    if sp is not None:
        tags.append("SPREAD_TIGHT" if sp<=0.06 else "SPREAD_OK" if sp<=0.10 else "SPREAD_WIDE")
    rsi=_num((f5.get("indicators") or {}).get("rsi14"))
    if rsi is not None:
        if rsi>=75: tags.append("RSI_OVERBOUGHT")
        elif rsi<=25: tags.append("RSI_OVERSOLD")
        else: tags.append("RSI_MID")
    return sorted(set(tags))

def _micro_score(package,direction):
    spot=(package or {}).get("decision_context",{}).get("market",{}).get("spot",{})
    imb=_num((spot.get("order_book") or {}).get("imbalance"))
    ratio=_num((spot.get("trade_flow") or {}).get("buy_sell_ratio"))
    score=0.0
    if imb is not None:
        if direction=="LONG": score += 0.45 if imb>=0.10 else -0.45 if imb<=-0.25 else 0
        else: score += 0.45 if imb<=-0.10 else -0.45 if imb>=0.25 else 0
    if ratio is not None:
        if direction=="LONG": score += 0.45 if ratio>=1.15 else -0.45 if ratio<=0.70 else 0
        else: score += 0.45 if ratio<=0.87 else -0.45 if ratio>=1.43 else 0
    return score

def _score(package,direction,strategy):
    f5=_frame(package,"5m"); f15=_frame(package,"15m"); f1=_frame(package,"1h"); f4=_frame(package,"4h")
    score=0.0
    parts=[]
    def add(cond,w,name):
        nonlocal score
        if cond:
            score+=w; parts.append(name)

    if strategy=="SCALP":
        add(_match(f1,"trend",direction),1.35,"1H_TREND")
        add(_match(f1,"structure",direction),0.85,"1H_STRUCTURE")
        add(_match(f15,"trend",direction),0.75,"15M_TREND")
        add(_match(f15,"structure",direction),0.85,"15M_STRUCTURE")
        add(_match(f15,"momentum",direction),1.00,"15M_MOMENTUM")
        add(_match(f5,"momentum",direction),1.10,"5M_MOMENTUM")
        add(_match(f5,"structure",direction),0.70,"5M_STRUCTURE")
        st=f5.get("structure") or {}
        add(bool(st.get("breakout_up") if direction=="LONG" else st.get("breakout_down")),1.25,"5M_BREAKOUT")
        ch=_num((f5.get("changes_pct") or {}).get("1bar"))
        add(ch is not None and ((direction=="LONG" and ch>0) or (direction=="SHORT" and ch<0)),0.45,"5M_BAR")
        vr=_num((f5.get("volume") or {}).get("ratio_to_avg20"))
        if vr is not None:
            add(vr>=1.5,1.00,"VOLUME_HIGH")
            if 0.9<=vr<1.5: score+=0.45; parts.append("VOLUME_OK")
        sp=_spread_pct(package)
        if sp is not None:
            if sp<=0.06: score+=0.55; parts.append("SPREAD_TIGHT")
            elif sp<=0.10: score+=0.20; parts.append("SPREAD_OK")
            else: score-=0.80
        if _oppose(f1,"trend",direction): score-=1.75
        if _oppose(f15,"trend",direction) and _oppose(f15,"structure",direction): score-=1.25
        rsi=_num((f5.get("indicators") or {}).get("rsi14"))
        if rsi is not None and ((direction=="LONG" and rsi>=75) or (direction=="SHORT" and rsi<=25)):
            score-=1.30
        score+=_micro_score(package,direction)
    else:
        add(_match(f4,"trend",direction),1.70,"4H_TREND")
        add(_match(f4,"structure",direction),0.90,"4H_STRUCTURE")
        add(_match(f1,"trend",direction),1.40,"1H_TREND")
        add(_match(f1,"structure",direction),1.00,"1H_STRUCTURE")
        add(_match(f1,"momentum",direction),0.80,"1H_MOMENTUM")
        add(_match(f15,"momentum",direction),0.80,"15M_MOMENTUM")
        st=f15.get("structure") or {}
        add(bool(st.get("breakout_up") if direction=="LONG" else st.get("breakout_down")),0.85,"15M_BREAKOUT")
        if _oppose(f4,"trend",direction): score-=2.25
        if _oppose(f1,"trend",direction): score-=1.50
        score+=0.5*_micro_score(package,direction)

    guards=(package or {}).get("guards",{})
    if guards.get("market_stale") or not guards.get("market_ok",False) or not guards.get("news_ok",False):
        score-=4.0
    if not guards.get("critical_news_verified",False):
        score-=3.0
    return score,parts

def _execution_eligibility(package,direction,strategy):
    reasons=[]
    g=(package or {}).get("guards",{})
    account=(package or {}).get("account_state",{})
    if g.get("market_stale") or not g.get("market_ok",False):
        reasons.append("MARKET_DATA_GUARD")
    if not g.get("news_ok",False):
        reasons.append("NEWS_DATA_GUARD")
    if not g.get("critical_news_verified",False):
        reasons.append("UNVERIFIED_HIGH_IMPACT_NEWS")
    if bool((g.get("cooldown") or {}).get("active")):
        reasons.append("COOLDOWN_ACTIVE")
    if bool((g.get("loss_streak_pause") or {}).get("active")):
        reasons.append("LOSS_STREAK_PAUSE")
    if bool(g.get("trading_halted")):
        reasons.append("TRADING_HALTED")
    if bool(g.get("asset_already_open")) and bool(config.ONE_POSITION_PER_ASSET):
        reasons.append("ASSET_ALREADY_OPEN")
    if int(account.get("open_positions") or 0)>=int(config.MAX_OPEN_POSITIONS):
        reasons.append("MAX_OPEN_POSITIONS")

    spread=_spread_pct(package)
    max_spread=float(config.ADAPTIVE_SCALP_MAX_SPREAD_PCT if strategy=="SCALP" else config.ADAPTIVE_NORMAL_MAX_SPREAD_PCT)
    if spread is None:
        reasons.append("SPREAD_UNAVAILABLE")
    elif spread>max_spread:
        reasons.append("SPREAD_TOO_WIDE")

    try:
        guard=(scalp_gate.entry_guard(package,direction) if strategy=="SCALP" else decision_gate.entry_guard(package,direction))
    except Exception as e:
        guard={"blocked":True,"reason":"ENTRY_GUARD_ERROR","error":str(e)}
    if guard.get("blocked"):
        reasons.append(str(guard.get("reason") or "ENTRY_GUARD_BLOCK"))

    return {
        "eligible":not reasons,
        "reasons":reasons,
        "spread_pct":spread,
        "max_spread_pct":max_spread,
        "entry_guard":guard,
    }

def _levels(package,direction,strategy,quality):
    entry=_entry(package)
    if not entry or entry<=0:
        return None
    if strategy=="SCALP":
        tf=_frame(package,"5m")
        atr_pct=_num((tf.get("indicators") or {}).get("atr_pct"))
        raw=max(0.12,(atr_pct or 0.12)*1.15)
        stop_pct=_clamp(raw,max(0.10,float(config.SCALP_MIN_STOP_PCT)+0.02),min(0.80,float(config.SCALP_MAX_STOP_PCT)))
        tier="PRIME" if quality>=78 else "FAST"
        rr1=float(config.SCALP_MIN_TP1_R)+0.10
        rr2=(float(config.SCALP_MIN_TP2_R)+0.10) if tier=="PRIME" else (float(config.SCALP_FAST_MIN_TP2_R)+0.12)
    else:
        tf=_frame(package,"1h")
        atr_pct=_num((tf.get("indicators") or {}).get("atr_pct"))
        stop_pct=_clamp(max(0.45,(atr_pct or 0.45)*1.10),0.45,2.00)
        tier=None
        rr1=float(config.MIN_TP1_R)+0.10
        rr2=float(config.MIN_TP2_R)+0.15

    risk=entry*(stop_pct/100.0)
    if direction=="LONG":
        stop=entry-risk; tp1=entry+risk*rr1; tp2=entry+risk*rr2
    else:
        stop=entry+risk; tp1=entry-risk*rr1; tp2=entry-risk*rr2
    return {
        "entry":entry,"stop_loss":stop,"take_profit_1":tp1,"take_profit_2":tp2,
        "stop_pct":stop_pct,"tp1_r":rr1,"tp2_r":rr2,"scalp_tier":tier,
    }

def _quality_from_score(score,strategy):
    # Neutral evidence sits near 50; coherent evidence rises into executable zone.
    scale=5.0 if strategy=="SCALP" else 5.5
    return _clamp(50.0+float(score)*scale,0.0,96.0)

def _candidate_id(asset,strategy,direction,candle_id):
    raw=f"{asset}|{strategy}|{direction}|{candle_id}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

def build_candidates(packages):
    out=[]
    for asset,p in (packages or {}).items():
        if asset not in set(config.ADAPTIVE_ALLOWED_ASSETS):
            continue
        candle=(_frame(p,"5m") or {}).get("last_confirmed_close_time_ms")
        if candle is None: continue
        for strategy in ("SCALP","NORMAL"):
            scored=[]
            for direction in ("LONG","SHORT"):
                score,parts=_score(p,direction,strategy)
                q=_quality_from_score(score,strategy)
                scored.append((q,score,direction,parts))
            q,score,direction,parts=max(scored,key=lambda x:x[0])
            lv=_levels(p,direction,strategy,q)
            if not lv: continue
            eligibility=_execution_eligibility(p,direction,strategy)
            candidate={
                "candidate_id":_candidate_id(asset,strategy,direction,candle),
                "created_at_utc":now().isoformat(),
                "candle_id":candle,
                "asset":asset,
                "strategy":strategy,
                "direction":direction,
                "base_score":round(score,3),
                "base_quality":round(q,2),
                "quality":round(q,2),
                "components":parts,
                "tags":_tags(p,direction,strategy),
                "spread_pct":_spread_pct(p),
                "execution_eligible":bool(eligibility.get("eligible")),
                "eligibility_reasons":eligibility.get("reasons") or [],
                "entry_guard":eligibility.get("entry_guard"),
                "time_horizon_minutes":(
                    int(config.ADAPTIVE_TRAINER_SCALP_HORIZON_MINUTES)
                    if strategy=="SCALP"
                    else int(config.ADAPTIVE_TRAINER_NORMAL_HORIZON_MINUTES)
                ),
                **lv,
            }
            out.append(candidate)
    return out

def _r_value(label,rr1,rr2,time_r=None):
    if label=="TP2_HIT": return float(rr2)
    if label=="TP1_ONLY": return max(0.5,float(rr1)*0.70)
    if label=="STOP_AFTER_TP1": return 0.0
    if label=="STOP_HIT": return -1.0
    if label=="AMBIGUOUS_BOTH_HIT": return 0.0
    if time_r is not None: return _clamp(time_r,-1.0,float(rr2))
    return 0.0

def _path(candidate,bars):
    direction=candidate["direction"]
    stop=float(candidate["stop_loss"]); tp1=float(candidate["take_profit_1"]); tp2=float(candidate["take_profit_2"])
    tp1_hit=False
    for bar in bars:
        hi=float(bar["high"]); lo=float(bar["low"])
        if direction=="LONG":
            hs=lo<=stop; h1=hi>=tp1; h2=hi>=tp2
        else:
            hs=hi>=stop; h1=lo<=tp1; h2=lo<=tp2
        if hs and (h1 or h2): return "AMBIGUOUS_BOTH_HIT",None
        if h2: return "TP2_HIT",float(candidate["tp2_r"])
        if h1: tp1_hit=True
        if hs: return ("STOP_AFTER_TP1" if tp1_hit else "STOP_HIT"),(0.0 if tp1_hit else -1.0)
    if tp1_hit: return "TP1_ONLY",max(0.5,float(candidate["tp1_r"])*0.70)
    last=float(bars[-1]["close"])
    entry=float(candidate["entry"]); risk=abs(entry-float(candidate["stop_loss"]))
    if risk<=0: return "OPEN_PATH",0.0
    pnl=(last-entry) if direction=="LONG" else (entry-last)
    r=pnl/risk
    label="TIME_EXIT_WIN" if r>=0.25 else "TIME_EXIT_LOSS" if r<=-0.25 else "FLAT"
    return label,_clamp(r,-1.0,float(candidate["tp2_r"]))

def evaluate_due(batch=None):
    candidates=_read(CANDIDATES)
    outcomes=_read(OUTCOMES)
    done={x.get("candidate_id") for x in outcomes}
    limit=int(batch or config.ADAPTIVE_TRAINER_OUTCOME_BATCH)
    utc=now(); pending=[]
    for c in reversed(candidates):
        cid=c.get("candidate_id")
        if not cid or cid in done: continue
        dt=_parse_ts(c.get("created_at_utc"))
        if not dt: continue
        horizon=int(config.ADAPTIVE_TRAINER_SCALP_HORIZON_MINUTES if c.get("strategy")=="SCALP" else config.ADAPTIVE_TRAINER_NORMAL_HORIZON_MINUTES)
        if utc>=dt+timedelta(minutes=horizon):
            pending.append((c,dt,horizon))
            if len(pending)>=limit: break
    if not pending:
        return {"status":"OK","evaluated":0}

    bars_cache={}; added=0
    for c,dt,horizon in reversed(pending):
        asset=c.get("asset")
        if asset not in ASSETS: continue
        if asset not in bars_cache:
            try:
                bars_cache[asset]=market_snapshot._okx_confirmed_candles(ASSETS[asset]["okx_swap"],"5m",300)
            except Exception:
                bars_cache[asset]=[]
        start=int(dt.timestamp()*1000); end=int((dt+timedelta(minutes=horizon)).timestamp()*1000)
        bars=[b for b in bars_cache[asset] if start<=int(b.get("open_time_ms",0))<=end]
        if not bars: continue
        label,r=_path(c,bars)
        row={
            "evaluated_at_utc":now().isoformat(),
            "candidate_id":c.get("candidate_id"),
            "created_at_utc":c.get("created_at_utc"),
            "asset":asset,"strategy":c.get("strategy"),"direction":c.get("direction"),
            "base_quality":c.get("base_quality"),"tags":c.get("tags") or [],
            "label":label,"r_result":round(float(r or 0),4),"horizon_minutes":horizon,
        }
        _append(OUTCOMES,row); done.add(c.get("candidate_id")); added+=1
    return {"status":"OK","evaluated":added}

def _similar_stats(candidate,outcomes=None):
    rows=outcomes if outcomes is not None else _read(OUTCOMES)
    if not rows:
        return {"samples":0,"weighted_samples":0.0,"avg_r":0.0,"adjustment":0.0}
    tags=set(candidate.get("tags") or [])
    num=0.0; den=0.0; samples=0
    for x in rows:
        if x.get("asset")!=candidate.get("asset"): continue
        if x.get("strategy")!=candidate.get("strategy"): continue
        weight=1.0
        if x.get("direction")==candidate.get("direction"): weight+=1.0
        xt=set(x.get("tags") or [])
        union=len(tags|xt); inter=len(tags&xt)
        if union: weight+=2.0*(inter/union)
        r=_num(x.get("r_result"))
        if r is None: continue
        num+=weight*r; den+=weight; samples+=1
    avg=(num/den) if den else 0.0
    # Strong shrinkage prevents a handful of lucky outcomes from dominating.
    shrink=samples/(samples+float(config.ADAPTIVE_TRAINER_LEARNING_PRIOR_SAMPLES))
    adj=_clamp(avg*shrink*float(config.ADAPTIVE_TRAINER_R_TO_QUALITY_MULT),-8.0,8.0)
    return {
        "samples":samples,
        "weighted_samples":round(den,2),
        "avg_r":round(avg,4),
        "adjustment":round(adj,2),
    }

def rank_candidates(packages):
    raw=build_candidates(packages)
    outcomes=_read(OUTCOMES)
    ranked=[]
    for c in raw:
        st=_similar_stats(c,outcomes)
        x=dict(c)
        x["learning"]=st
        x["quality"]=round(_clamp(float(c["base_quality"])+float(st["adjustment"]),0,96),2)
        # Recompute tier after learned quality while keeping exact risk-aligned levels.
        if x["strategy"]=="SCALP":
            x["scalp_tier"]="PRIME" if x["quality"]>=78 else "FAST"
            if x["scalp_tier"]=="PRIME":
                x["tp1_r"]=float(config.SCALP_MIN_TP1_R)+0.10
                x["tp2_r"]=float(config.SCALP_MIN_TP2_R)+0.10
            else:
                x["tp1_r"]=float(config.SCALP_FAST_MIN_TP1_R)+0.10
                x["tp2_r"]=float(config.SCALP_FAST_MIN_TP2_R)+0.12
            risk=abs(float(x["entry"])-float(x["stop_loss"]))
            if x["direction"]=="LONG":
                x["take_profit_1"]=float(x["entry"])+risk*x["tp1_r"]
                x["take_profit_2"]=float(x["entry"])+risk*x["tp2_r"]
            else:
                x["take_profit_1"]=float(x["entry"])-risk*x["tp1_r"]
                x["take_profit_2"]=float(x["entry"])-risk*x["tp2_r"]
        ranked.append(x)
    ranked.sort(key=lambda x:(float(x.get("quality") or 0),float(x.get("base_score") or 0)),reverse=True)
    return ranked

def record_shadow(candidates):
    recent={x.get("candidate_id") for x in _read(CANDIDATES)[-1000:]}
    n=0
    for c in candidates:
        if float(c.get("base_quality") or 0)<float(config.ADAPTIVE_TRAINER_SHADOW_MIN_QUALITY):
            continue
        if c.get("candidate_id") in recent: continue
        _append(CANDIDATES,c); recent.add(c.get("candidate_id")); n+=1
    return {"status":"OK","recorded":n}

def process(packages):
    evaluated=evaluate_due()
    ranked=rank_candidates(packages)
    recorded=record_shadow(ranked)
    actionable=[
        c for c in ranked
        if bool(c.get("execution_eligible"))
        and float(c.get("quality") or 0)>=float(config.ADAPTIVE_TRAINER_MIN_MODEL_QUALITY)
    ]
    return {
        "status":"OK",
        "evaluated":evaluated.get("evaluated",0),
        "recorded":recorded.get("recorded",0),
        "ranked":ranked,
        "actionable":actionable,
        "best":actionable[0] if actionable else (ranked[0] if ranked else None),
        "summary":summary(168),
    }

def summary(hours=168):
    cutoff=now()-timedelta(hours=float(hours))
    outcomes=[x for x in _read(OUTCOMES) if (_parse_ts(x.get("evaluated_at_utc")) or datetime.min.replace(tzinfo=timezone.utc))>=cutoff]
    candidates=[x for x in _read(CANDIDATES) if (_parse_ts(x.get("created_at_utc")) or datetime.min.replace(tzinfo=timezone.utc))>=cutoff]
    labels=Counter(str(x.get("label") or "UNKNOWN") for x in outcomes)
    by_asset=defaultdict(lambda:{"n":0,"r":0.0})
    by_strategy=defaultdict(lambda:{"n":0,"r":0.0})
    for x in outcomes:
        r=float(x.get("r_result") or 0)
        for d,key in ((by_asset,str(x.get("asset") or "UNKNOWN")),(by_strategy,str(x.get("strategy") or "UNKNOWN"))):
            d[key]["n"]+=1; d[key]["r"]+=r
    def finish(d):
        return {k:{"samples":v["n"],"avg_r":round(v["r"]/v["n"],3) if v["n"] else 0.0} for k,v in d.items()}
    total_r=sum(float(x.get("r_result") or 0) for x in outcomes)
    return {
        "hours":float(hours),
        "shadow_candidates":len(candidates),
        "evaluated":len(outcomes),
        "avg_r":round(total_r/len(outcomes),3) if outcomes else 0.0,
        "labels":dict(labels),
        "by_asset":finish(by_asset),
        "by_strategy":finish(by_strategy),
    }

def telegram_text(hours=168):
    s=summary(hours)
    l=s.get("labels",{})
    lines=[
        f"🧪 <b>ASTRA TRAINER — {int(float(hours))}h</b>","",
        f"Shadow practice: <b>{s.get('shadow_candidates',0)}</b>",
        f"Evaluated: <b>{s.get('evaluated',0)}</b>",
        f"Average shadow R: <b>{s.get('avg_r',0):.3f}R</b>",
        f"TP2: <b>{l.get('TP2_HIT',0)}</b>",
        f"TP1 only: <b>{l.get('TP1_ONLY',0)}</b>",
        f"Stops: <b>{l.get('STOP_HIT',0)}</b>",
        f"Time-exit wins: <b>{l.get('TIME_EXIT_WIN',0)}</b>",
        f"Time-exit losses: <b>{l.get('TIME_EXIT_LOSS',0)}</b>","",
        "<b>By asset:</b>",
    ]
    for a,v in sorted((s.get("by_asset") or {}).items()):
        lines.append(f"• {a}: {v.get('samples',0)} samples | {v.get('avg_r',0):.3f}R")
    lines+=["","Это обучение на теневых сделках без OpenAI API и без ордеров."]
    return "\n".join(lines)

if __name__=="__main__":
    print(json.dumps(summary(),ensure_ascii=False,indent=2))

#!/usr/bin/env python3
"""ASTRA Strategy Tournament v5.

Four independent strategy archetypes compete in shadow mode:
- TREND_FOLLOW
- BREAKOUT
- MEAN_REVERSION
- MOMENTUM

Only candidates backed by positive empirical NET-R statistics become CHAMPION
candidates and may reach GPT/Astra and OKX Demo. Challengers continue learning
without orders or OpenAI calls.

The tournament can bootstrap statistics from existing costaware_v4 Trainer
outcomes by retro-classifying their tags. That preserves useful evidence while
keeping the new archetype-specific shadow journal separate.
"""
import json, math, hashlib
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

import config
import adaptive_trainer
import market_snapshot
from asset_map import ASSETS

DIR=Path(config.STATE_DIR)
CANDIDATES=DIR/"strategy_tournament_candidates.jsonl"
OUTCOMES=DIR/"strategy_tournament_outcomes.jsonl"

def now():
    return datetime.now(timezone.utc)

def _parse_ts(x):
    try:
        return datetime.fromisoformat(str(x or "").replace("Z","+00:00"))
    except Exception:
        return None

def _num(x):
    try:return float(x)
    except Exception:return None

def _clamp(x,lo,hi):
    try:return max(lo,min(hi,float(x)))
    except Exception:return lo

def _append(path,row):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("a",encoding="utf-8") as f:
        f.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")
    _compact(path)

def _compact(path):
    try:
        cap=float(config.TOURNAMENT_LOG_MAX_MB)*1024*1024
        if cap<=0 or not path.exists() or path.stat().st_size<=cap:return
        target=int(cap*0.55)
        with path.open("rb") as f:
            f.seek(max(0,path.stat().st_size-target));chunk=f.read()
        i=chunk.find(b"\n")
        if i>=0:chunk=chunk[i+1:]
        tmp=path.with_suffix(path.suffix+".tmp")
        tmp.write_bytes(chunk);tmp.replace(path)
    except Exception:
        pass

def _read(path):
    out=[]
    try:
        with path.open("r",encoding="utf-8") as f:
            for line in f:
                try:
                    x=json.loads(line)
                    if isinstance(x,dict):out.append(x)
                except Exception:continue
    except Exception:
        pass
    return out

def _frame(p,tf):
    return adaptive_trainer._frame(p,tf)

def _regime_base(x):
    return str(x or "UNKNOWN").split("|")[0]

def _rsi(p,tf="5m"):
    return _num((_frame(p,tf).get("indicators") or {}).get("rsi14"))

def _close(p,tf="5m"):
    return _num(_frame(p,tf).get("close"))

def _ema(p,tf="5m",key="ema20"):
    return _num((_frame(p,tf).get("indicators") or {}).get(key))

def _atr_pct(p,tf="5m"):
    return _num((_frame(p,tf).get("indicators") or {}).get("atr_pct"))

def _vol_ratio(p,tf="5m"):
    return _num((_frame(p,tf).get("volume") or {}).get("ratio_to_avg20"))

def _change(p,tf="5m",key="1bar"):
    return _num((_frame(p,tf).get("changes_pct") or {}).get(key))

def _breakout(p,tf,direction):
    st=_frame(p,tf).get("structure") or {}
    return bool(st.get("breakout_up") if direction=="LONG" else st.get("breakout_down"))

def _match(p,tf,key,direction):
    return adaptive_trainer._match(_frame(p,tf),key,direction)

def _oppose(p,tf,key,direction):
    return adaptive_trainer._oppose(_frame(p,tf),key,direction)

def _micro(p,direction):
    return adaptive_trainer._micro_score(p,direction)

def _trend_follow_score(p,direction):
    score=0.0;parts=[]
    def add(cond,w,name):
        nonlocal score
        if cond:score+=w;parts.append(name)
    add(_match(p,"4h","trend",direction),1.6,"4H_TREND")
    add(_match(p,"4h","structure",direction),0.8,"4H_STRUCTURE")
    add(_match(p,"1h","trend",direction),1.7,"1H_TREND")
    add(_match(p,"1h","structure",direction),1.0,"1H_STRUCTURE")
    add(_match(p,"15m","trend",direction),0.7,"15M_TREND")
    add(_match(p,"15m","momentum",direction),0.7,"15M_MOMENTUM")
    add(_match(p,"5m","momentum",direction),0.35,"5M_MOMENTUM")
    if _oppose(p,"4h","trend",direction):score-=2.4
    if _oppose(p,"1h","trend",direction):score-=1.8
    close=_close(p,"15m");ema20=_ema(p,"15m","ema20");atr=_atr_pct(p,"15m")
    if close and ema20 and atr:
        dist=abs(close-ema20)/close*100.0
        if dist<=max(0.15,atr*0.8):
            score+=0.7;parts.append("PULLBACK_NEAR_EMA20")
        elif dist>max(0.8,atr*2.0):
            score-=0.8
    score+=0.35*_micro(p,direction)
    return score,parts

def _breakout_score(p,direction):
    score=0.0;parts=[]
    def add(cond,w,name):
        nonlocal score
        if cond:score+=w;parts.append(name)
    add(_breakout(p,"5m",direction),2.0,"5M_BREAKOUT")
    add(_breakout(p,"15m",direction),1.4,"15M_BREAKOUT")
    add(_match(p,"1h","trend",direction),1.0,"1H_TREND")
    add(_match(p,"15m","momentum",direction),1.0,"15M_MOMENTUM")
    add(_match(p,"5m","momentum",direction),1.0,"5M_MOMENTUM")
    vr=_vol_ratio(p,"5m")
    if vr is not None:
        if vr>=1.5:score+=1.3;parts.append("VOLUME_HIGH")
        elif vr>=1.0:score+=0.65;parts.append("VOLUME_OK")
        elif vr<0.7:score-=0.8
    ch=_change(p,"5m","1bar")
    if ch is not None:
        if (direction=="LONG" and ch>0.12) or (direction=="SHORT" and ch<-0.12):
            score+=0.7;parts.append("IMPULSE_BAR")
    if _oppose(p,"1h","trend",direction):score-=1.5
    score+=0.45*_micro(p,direction)
    return score,parts

def _momentum_score(p,direction):
    score=0.0;parts=[]
    def add(cond,w,name):
        nonlocal score
        if cond:score+=w;parts.append(name)
    add(_match(p,"15m","momentum",direction),1.5,"15M_MOMENTUM")
    add(_match(p,"5m","momentum",direction),1.7,"5M_MOMENTUM")
    add(_match(p,"5m","structure",direction),0.65,"5M_STRUCTURE")
    add(_match(p,"1h","trend",direction),0.65,"1H_TREND")
    vr=_vol_ratio(p,"5m")
    if vr is not None:
        if vr>=1.4:score+=1.0;parts.append("VOLUME_HIGH")
        elif vr>=0.9:score+=0.45;parts.append("VOLUME_OK")
        else:score-=0.55
    ch1=_change(p,"5m","1bar");ch3=_change(p,"5m","3bar")
    if ch1 is not None and ((direction=="LONG" and ch1>0) or (direction=="SHORT" and ch1<0)):
        score+=0.6;parts.append("BAR_DIRECTION")
    if ch3 is not None and ((direction=="LONG" and ch3>0.15) or (direction=="SHORT" and ch3<-0.15)):
        score+=0.65;parts.append("3BAR_IMPULSE")
    score+=0.85*_micro(p,direction)
    rsi=_rsi(p)
    if rsi is not None and ((direction=="LONG" and rsi>78) or (direction=="SHORT" and rsi<22)):
        score-=1.0
    return score,parts

def _mean_reversion_score(p,direction):
    score=0.0;parts=[]
    regime=_regime_base(adaptive_trainer._market_regime(p))
    if regime=="RANGE":score+=2.2;parts.append("RANGE")
    elif regime=="MIXED":score+=1.0;parts.append("MIXED")
    elif regime.startswith("TREND"):score-=1.5

    rsi=_rsi(p)
    close=_close(p);ema20=_ema(p);atr=_atr_pct(p)
    if rsi is not None:
        if direction=="LONG":
            if rsi<=28:score+=2.0;parts.append("RSI_OVERSOLD")
            elif rsi<=36:score+=1.0;parts.append("RSI_LOW")
            elif rsi>=60:score-=1.0
        else:
            if rsi>=72:score+=2.0;parts.append("RSI_OVERBOUGHT")
            elif rsi>=64:score+=1.0;parts.append("RSI_HIGH")
            elif rsi<=40:score-=1.0
    if close and ema20 and atr:
        dev=(close-ema20)/close*100.0
        threshold=max(0.12,atr*0.7)
        if direction=="LONG" and dev<=-threshold:
            score+=1.4;parts.append("BELOW_EMA20")
        elif direction=="SHORT" and dev>=threshold:
            score+=1.4;parts.append("ABOVE_EMA20")
    # Mean reversion should not fight a strongly aligned 1H+4H trend.
    if _oppose(p,"1h","trend",direction) and _oppose(p,"4h","trend",direction):
        score-=1.7
    score+=0.25*_micro(p,direction)
    return score,parts

def _score(p,archetype,direction):
    if archetype=="TREND_FOLLOW":return _trend_follow_score(p,direction)
    if archetype=="BREAKOUT":return _breakout_score(p,direction)
    if archetype=="MEAN_REVERSION":return _mean_reversion_score(p,direction)
    return _momentum_score(p,direction)

def _strategy_mode(archetype):
    return "NORMAL" if archetype=="TREND_FOLLOW" else "SCALP"

def _quality(score,archetype):
    scale=5.2 if archetype=="TREND_FOLLOW" else 5.0
    return _clamp(48.0+float(score)*scale,0.0,96.0)

def _id(asset,archetype,direction,candle):
    raw=f"{asset}|{archetype}|{direction}|{candle}|{config.TRAINER_GEOMETRY_VERSION}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:18]

def _reprice_tier(x):
    x=dict(x)
    if x.get("strategy")!="SCALP":return x
    tier="PRIME" if float(x.get("quality") or 0)>=max(78.0,float(config.SCALP_MIN_TRADE_CONFIDENCE)) else "FAST"
    x["scalp_tier"]=tier
    if tier=="PRIME":
        x["tp1_r"]=float(config.SCALP_MIN_TP1_R)+0.10
        x["tp2_r"]=float(config.SCALP_MIN_TP2_R)+0.10
    else:
        x["tp1_r"]=float(config.SCALP_FAST_MIN_TP1_R)+0.10
        x["tp2_r"]=float(config.SCALP_FAST_MIN_TP2_R)+0.12
    entry=float(x["entry"]);risk=abs(entry-float(x["stop_loss"]))
    if x["direction"]=="LONG":
        x["take_profit_1"]=entry+risk*x["tp1_r"];x["take_profit_2"]=entry+risk*x["tp2_r"]
    else:
        x["take_profit_1"]=entry-risk*x["tp1_r"];x["take_profit_2"]=entry-risk*x["tp2_r"]
    return x

def build_candidates(packages):
    out=[]
    for asset,p in (packages or {}).items():
        if asset not in set(config.ADAPTIVE_ALLOWED_ASSETS):continue
        candle=(_frame(p,"5m") or {}).get("last_confirmed_close_time_ms")
        if candle is None:continue
        for archetype in config.TOURNAMENT_ARCHETYPES:
            scored=[]
            for direction in ("LONG","SHORT"):
                s,parts=_score(p,archetype,direction)
                scored.append((_quality(s,archetype),s,direction,parts))
            q,score,direction,parts=max(scored,key=lambda x:x[0])
            strategy=_strategy_mode(archetype)
            lv=adaptive_trainer._levels(p,direction,strategy,q)
            if not lv:continue
            eligibility=adaptive_trainer._execution_eligibility(p,direction,strategy)
            market=(p or {}).get("decision_context",{}).get("market",{})
            perp=market.get("perp_okx") or {}
            c={
                "candidate_id":_id(asset,archetype,direction,candle),
                "created_at_utc":now().isoformat(),
                "candle_id":candle,
                "asset":asset,
                "archetype":archetype,
                "strategy":strategy,
                "direction":direction,
                "base_score":round(score,3),
                "base_quality":round(q,2),
                "quality":round(q,2),
                "components":parts,
                "tags":sorted(set(adaptive_trainer._tags(p,direction,strategy)+["ARCH_"+archetype])),
                "market_regime":adaptive_trainer._market_regime(p),
                "spread_pct":adaptive_trainer._spread_pct(p),
                "funding_rate":_num(perp.get("funding_rate")),
                "execution_eligible":bool(eligibility.get("eligible")),
                "eligibility_reasons":eligibility.get("reasons") or [],
                "entry_guard":eligibility.get("entry_guard"),
                "time_horizon_minutes":(
                    int(config.ADAPTIVE_TRAINER_NORMAL_HORIZON_MINUTES)
                    if strategy=="NORMAL" else int(config.ADAPTIVE_TRAINER_SCALP_HORIZON_MINUTES)
                ),
                **lv,
            }
            c=adaptive_trainer._apply_cost_aware_geometry(c)
            out.append(c)
    return out

def infer_archetype(row):
    a=str(row.get("archetype") or "").upper()
    if a in set(config.TOURNAMENT_ARCHETYPES):return a
    tags=set(str(x) for x in (row.get("tags") or []))
    regime=_regime_base(row.get("market_regime"))
    strategy=str(row.get("strategy") or "").upper()
    if "BREAKOUT" in tags or "5M_BREAKOUT" in tags or "15M_BREAKOUT" in tags:
        return "BREAKOUT"
    if regime in {"RANGE","MIXED"} and ({"RSI_OVERBOUGHT","RSI_OVERSOLD"}&tags):
        return "MEAN_REVERSION"
    if {"5M_MOM_MATCH","15M_MOM_MATCH"}<=tags or ("VOL_HIGH" in tags and "5M_MOM_MATCH" in tags):
        return "MOMENTUM"
    if "1H_TREND_MATCH" in tags and ("4H_TREND_MATCH" in tags or "1H_STRUCT_MATCH" in tags):
        return "TREND_FOLLOW"
    return "TREND_FOLLOW" if strategy=="NORMAL" else "MOMENTUM"

def _bootstrap_rows():
    if not config.TOURNAMENT_BOOTSTRAP_V4_OUTCOMES:return []
    rows=[]
    try:
        base=adaptive_trainer._read(adaptive_trainer.OUTCOMES)
    except Exception:
        base=[]
    for x in base:
        if x.get("geometry_version")!=config.TRAINER_GEOMETRY_VERSION:continue
        y=dict(x)
        y["archetype"]=infer_archetype(y)
        y["source"]="BOOTSTRAP_V4_GENERIC"
        rows.append(y)
    return rows

def evidence_rows():
    own=_read(OUTCOMES)
    return _bootstrap_rows()+own

def _metrics(rows):
    rows=sorted(rows,key=lambda x:str(x.get("evaluated_at_utc") or x.get("created_at_utc") or ""))
    vals=[]
    for x in rows:
        r=_num(x.get("net_r") if x.get("net_r") is not None else x.get("r_result"))
        if r is not None:vals.append(r)
    n=len(vals)
    if not n:
        return {"samples":0,"avg_net_r":0.0,"profit_factor":0.0,"win_rate":0.0,"max_drawdown_r":0.0,"lower_bound_r":-999.0}
    avg=sum(vals)/n
    gp=sum(v for v in vals if v>0);gl=-sum(v for v in vals if v<0)
    pf=(gp/gl) if gl>1e-12 else (99.0 if gp>0 else 0.0)
    wins=sum(1 for v in vals if v>0)
    equity=0.0;peak=0.0;maxdd=0.0
    for v in vals:
        equity+=v;peak=max(peak,equity);maxdd=max(maxdd,peak-equity)
    var=sum((v-avg)**2 for v in vals)/(n-1) if n>1 else 0.0
    se=math.sqrt(var)/math.sqrt(n) if n else 0.0
    lower=avg-se
    return {
        "samples":n,
        "avg_net_r":round(avg,4),
        "profit_factor":round(pf,3),
        "win_rate":round(wins/n,4),
        "max_drawdown_r":round(maxdd,3),
        "lower_bound_r":round(lower,4),
    }

def _candidate_stats(candidate,rows=None):
    rows=rows if rows is not None else evidence_rows()
    asset=candidate.get("asset");arch=candidate.get("archetype");direction=candidate.get("direction")
    regime=_regime_base(candidate.get("market_regime"))
    broad=[x for x in rows if x.get("asset")==asset and infer_archetype(x)==arch and x.get("direction")==direction]
    exact=[x for x in broad if _regime_base(x.get("market_regime"))==regime]
    overall=[x for x in rows if x.get("asset")==asset and infer_archetype(x)==arch]
    return {
        "broad":_metrics(broad),
        "regime":_metrics(exact),
        "overall":_metrics(overall),
        "regime_key":regime,
    }

def champion_gate(candidate,rows=None):
    st=_candidate_stats(candidate,rows)
    b=st["broad"];r=st["regime"]
    reasons=[]
    if b["samples"]<int(config.TOURNAMENT_MIN_SAMPLES):reasons.append("BROAD_SAMPLES")
    if b["avg_net_r"]<float(config.TOURNAMENT_MIN_AVG_NET_R):reasons.append("BROAD_NET_R")
    if b["profit_factor"]<float(config.TOURNAMENT_MIN_PROFIT_FACTOR):reasons.append("BROAD_PROFIT_FACTOR")
    if b["max_drawdown_r"]>float(config.TOURNAMENT_MAX_DRAWDOWN_R):reasons.append("BROAD_DRAWDOWN")
    if b["lower_bound_r"]<float(config.TOURNAMENT_MIN_LOWER_BOUND_R):reasons.append("BROAD_LOWER_BOUND")
    # Regime evidence protects against a strategy that is good overall but bad
    # in the market state currently being traded.
    min_regime=max(15,min(30,int(config.TOURNAMENT_MIN_SAMPLES)//2))
    if r["samples"]<min_regime:reasons.append("REGIME_SAMPLES")
    if r["samples"]>=min_regime and r["avg_net_r"]<0.0:reasons.append("REGIME_NET_R")
    if r["samples"]>=min_regime and r["profit_factor"]<1.0:reasons.append("REGIME_PROFIT_FACTOR")

    champion=not reasons
    mature=champion and b["samples"]>=int(config.TOURNAMENT_MATURE_SAMPLES)
    risk_mult=(
        float(config.TOURNAMENT_RISK_MULTIPLIER_MATURE)
        if mature else float(config.TOURNAMENT_RISK_MULTIPLIER_NEW)
    )
    return {
        "champion":champion,
        "tier":"MATURE" if mature else "NEW" if champion else "CHALLENGER",
        "risk_multiplier":risk_mult if champion else 0.0,
        "reasons":reasons,
        "stats":st,
    }

def rank_candidates(packages):
    raw=build_candidates(packages)
    rows=evidence_rows()
    ranked=[]
    for c in raw:
        gate=champion_gate(c,rows)
        broad=gate["stats"]["broad"]
        shrink=broad["samples"]/(broad["samples"]+30.0)
        adj=_clamp(float(broad["avg_net_r"])*shrink*6.0,-5.0,5.0)
        x=dict(c)
        x["empirical_adjustment"]=round(adj,2)
        x["quality"]=round(_clamp(float(x["base_quality"])+adj,0.0,96.0),2)
        x=_reprice_tier(x)
        x["champion_gate"]=gate
        x["tournament_tier"]=gate["tier"]
        x["tournament_risk_multiplier"]=gate["risk_multiplier"]
        ranked.append(x)
    ranked.sort(key=lambda x:(
        1 if (x.get("champion_gate") or {}).get("champion") else 0,
        float(((x.get("champion_gate") or {}).get("stats") or {}).get("broad",{}).get("avg_net_r") or -99),
        float(x.get("quality") or 0)
    ),reverse=True)
    return ranked

def record_shadow(candidates):
    recent={x.get("candidate_id") for x in _read(CANDIDATES)[-3000:]}
    n=0
    for c in candidates:
        if float(c.get("base_quality") or 0)<float(config.TOURNAMENT_SHADOW_MIN_QUALITY):continue
        if c.get("candidate_id") in recent:continue
        _append(CANDIDATES,c);recent.add(c.get("candidate_id"));n+=1
    return n

def evaluate_due(batch=None):
    candidates=_read(CANDIDATES);outcomes=_read(OUTCOMES)
    done={x.get("candidate_id") for x in outcomes}
    pending=[];utc=now();limit=int(batch or config.TOURNAMENT_OUTCOME_BATCH)
    for c in reversed(candidates):
        cid=c.get("candidate_id")
        if not cid or cid in done:continue
        dt=_parse_ts(c.get("created_at_utc"))
        if not dt:continue
        horizon=int(c.get("time_horizon_minutes") or 60)
        if utc>=dt+timedelta(minutes=horizon):
            pending.append((c,dt,horizon))
            if len(pending)>=limit:break
    if not pending:return {"status":"OK","evaluated":0}
    bars_cache={};added=0
    for c,dt,horizon in reversed(pending):
        asset=str(c.get("asset") or "")
        inst=(ASSETS.get(asset) or {}).get("okx_swap")
        if not inst:continue
        if asset not in bars_cache:
            try:bars_cache[asset]=market_snapshot._okx_confirmed_candles(inst,"5m",300)
            except Exception:bars_cache[asset]=[]
        start=int(dt.timestamp()*1000);end=int((dt+timedelta(minutes=horizon)).timestamp()*1000)
        bars=[b for b in bars_cache[asset] if start<=int(b.get("open_time_ms",0))<=end]
        if not bars:continue
        label,gross=adaptive_trainer._path(c,bars)
        cost=adaptive_trainer._estimated_cost(c)
        gross=float(gross or 0.0);net=gross-float(cost.get("cost_r") or 0.0)
        row={
            "evaluated_at_utc":now().isoformat(),
            "candidate_id":c.get("candidate_id"),
            "created_at_utc":c.get("created_at_utc"),
            "asset":asset,
            "archetype":c.get("archetype"),
            "strategy":c.get("strategy"),
            "direction":c.get("direction"),
            "market_regime":c.get("market_regime"),
            "geometry_version":c.get("geometry_version"),
            "tags":c.get("tags") or [],
            "label":label,
            "gross_r":round(gross,4),
            "estimated_cost_r":round(float(cost.get("cost_r") or 0.0),4),
            "net_r":round(net,4),
            "r_result":round(net,4),
            "horizon_minutes":horizon,
            "source":"TOURNAMENT_V5",
        }
        _append(OUTCOMES,row);done.add(c.get("candidate_id"));added+=1
    return {"status":"OK","evaluated":added}

def process(packages):
    ev=evaluate_due()
    ranked=rank_candidates(packages)
    recorded=record_shadow(ranked)
    champions=[
        x for x in ranked
        if bool((x.get("champion_gate") or {}).get("champion"))
        and bool(x.get("execution_eligible"))
        and bool(x.get("cost_efficient"))
    ]
    return {
        "status":"OK",
        "evaluated":ev.get("evaluated",0),
        "recorded":recorded,
        "ranked":ranked,
        "champions":champions,
        "best":champions[0] if champions else (ranked[0] if ranked else None),
        "summary":summary(168),
    }

def _broad_groups(rows):
    groups=defaultdict(list)
    for x in rows:
        asset=str(x.get("asset") or "UNKNOWN")
        arch=infer_archetype(x)
        direction=str(x.get("direction") or "UNKNOWN")
        groups[(asset,arch,direction)].append(x)
    return groups

def summary(hours=168):
    cutoff=now()-timedelta(hours=float(hours))
    own=[x for x in _read(OUTCOMES) if (_parse_ts(x.get("evaluated_at_utc")) or datetime.min.replace(tzinfo=timezone.utc))>=cutoff]
    boot=[
        x for x in _bootstrap_rows()
        if (_parse_ts(x.get("evaluated_at_utc")) or datetime.min.replace(tzinfo=timezone.utc))>=cutoff
    ]
    rows=boot+own
    leaderboard=[]
    for (asset,arch,direction),bucket in _broad_groups(rows).items():
        m=_metrics(bucket)
        champion=(
            m["samples"]>=int(config.TOURNAMENT_MIN_SAMPLES)
            and m["avg_net_r"]>=float(config.TOURNAMENT_MIN_AVG_NET_R)
            and m["profit_factor"]>=float(config.TOURNAMENT_MIN_PROFIT_FACTOR)
            and m["max_drawdown_r"]<=float(config.TOURNAMENT_MAX_DRAWDOWN_R)
            and m["lower_bound_r"]>=float(config.TOURNAMENT_MIN_LOWER_BOUND_R)
        )
        leaderboard.append({
            "asset":asset,"archetype":arch,"direction":direction,
            **m,"broad_champion":champion,
        })
    leaderboard.sort(key=lambda x:(1 if x["broad_champion"] else 0,x["avg_net_r"],x["samples"]),reverse=True)
    return {
        "hours":float(hours),
        "shadow_candidates":len([
            x for x in _read(CANDIDATES)
            if (_parse_ts(x.get("created_at_utc")) or datetime.min.replace(tzinfo=timezone.utc))>=cutoff
        ]),
        "own_evaluated":len(own),
        "bootstrap_evaluated":len(boot),
        "evidence_total":len(rows),
        "leaderboard":leaderboard[:20],
        "broad_champions":[x for x in leaderboard if x["broad_champion"]][:10],
    }

def telegram_text(hours=168):
    s=summary(hours)
    lines=[
        f"🏆 <b>STRATEGY TOURNAMENT v5 — {int(float(hours))}h</b>","",
        f"Shadow challengers: <b>{s.get('shadow_candidates',0)}</b>",
        f"Own evaluated: <b>{s.get('own_evaluated',0)}</b>",
        f"Bootstrap v4 evidence: <b>{s.get('bootstrap_evaluated',0)}</b>",
        f"Broad champions: <b>{len(s.get('broad_champions') or [])}</b>","",
        "<b>Leaderboard:</b>",
    ]
    board=s.get("leaderboard") or []
    if not board:
        lines.append("• пока нет статистики")
    for x in board[:10]:
        icon="🏆" if x.get("broad_champion") else "🧪"
        lines.append(
            f"{icon} {x['asset']} {x['archetype']} {x['direction']} | "
            f"n={x['samples']} | {x['avg_net_r']:+.3f}R | PF {x['profit_factor']:.2f}"
        )
    lines += [
        "",
        "В OKX Demo допускается только кандидат, который проходит и broad, и текущий regime gate.",
        "Challengers продолжают shadow-обучение без OpenAI и без ордеров.",
    ]
    return "\n".join(lines)

if __name__=="__main__":
    print(json.dumps(summary(),ensure_ascii=False,indent=2))

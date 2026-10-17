#!/usr/bin/env python3
"""ASTRA Multi-Market Trainer v3.

Shadow-only laboratories for Gold and DeFi. No orders and no OpenAI calls.
The lab:
- selects liquid DeFi swaps dynamically from public OKX data,
- builds Gold / DeFi hypothetical candidates,
- evaluates them from later OKX candles,
- learns on NET R after estimated fees/spread/slippage/funding,
- keeps regime-specific statistics,
- applies a protocol-security halt for DeFi shadow candidate generation.

Crypto execution remains owned by adaptive_trainer/adaptive_engine.
"""
import json,time,hashlib,threading
from collections import Counter,defaultdict
from datetime import datetime,timezone,timedelta
from pathlib import Path

import config
import market_snapshot
import news_snapshot
import adaptive_trainer
import defi_universe
from asset_map import ASSETS

DIR=Path(config.STATE_DIR)
CANDIDATES=DIR/"multi_market_trainer_candidates.jsonl"
OUTCOMES=DIR/"multi_market_trainer_outcomes.jsonl"
STATE_FILE=DIR/"multi_market_trainer_state.json"
NEWS_CACHE=DIR/"multi_market_news_cache.json"

STATE={
    "status":"STARTING",
    "last_error":None,
    "last_run_utc":None,
    "last_gold_scan_utc":None,
    "last_defi_scan_utc":None,
    "last_universe":None,
    "last_result":None,
}

SECURITY_WORDS=(
    "exploit","exploited","hack","hacked","drain","drained","vulnerability",
    "oracle attack","oracle failure","depeg","de-peg","compromised","emergency pause",
    "security incident","attack vector","stolen funds"
)

def now():
    return datetime.now(timezone.utc)

def _parse_ts(x):
    try:return datetime.fromisoformat(str(x or "").replace("Z","+00:00"))
    except Exception:return None

def _num(x):
    try:return float(x)
    except Exception:return None

def _clamp(x,lo=0.0,hi=100.0):
    try:return max(lo,min(hi,float(x)))
    except Exception:return lo

def _load_json(path,default):
    try:
        x=json.loads(path.read_text(encoding="utf-8"))
        return x if isinstance(x,type(default)) else default
    except Exception:
        return default

def _atomic_json(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
    tmp.replace(path)

def _append(path,row):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("a",encoding="utf-8") as f:
        f.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")
    _compact(path)

def _compact(path):
    try:
        cap=float(config.MULTI_MARKET_TRAINER_LOG_MAX_MB)*1024*1024
        if cap<=0 or not path.exists() or path.stat().st_size<=cap:return
        target=int(cap*0.55)
        with path.open("rb") as f:
            f.seek(max(0,path.stat().st_size-target)); chunk=f.read()
        i=chunk.find(b"\n")
        if i>=0:chunk=chunk[i+1:]
        tmp=path.with_suffix(path.suffix+".compact.tmp")
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

def _state():
    return _load_json(STATE_FILE,{})

def _save_state(x):
    _atomic_json(STATE_FILE,x)

def _due(ts,minutes):
    dt=_parse_ts(ts)
    return (dt is None) or ((now()-dt).total_seconds()>=float(minutes)*60.0)

def _news(asset):
    cache=_load_json(NEWS_CACHE,{})
    row=cache.get(asset) or {}
    ts=_parse_ts(row.get("at_utc"))
    max_age=float(config.DEFI_LAB_NEWS_REFRESH_MINUTES)
    if asset=="XAU":
        max_age=min(max_age,float(config.GOLD_TRAINER_INTERVAL_MINUTES))
    if ts and (now()-ts).total_seconds()<max_age*60 and isinstance(row.get("data"),dict):
        return row["data"]
    data=news_snapshot.snapshot(asset,12)
    cache[asset]={"at_utc":now().isoformat(),"data":data}
    _atomic_json(NEWS_CACHE,cache)
    return data

def _package(asset):
    m=market_snapshot.snapshot(asset)
    n=_news(asset)
    generated=_parse_ts(m.get("generated_at_utc"))
    age=(now()-generated).total_seconds() if generated else 10**9
    guards={
        "market_ok":m.get("data_quality",{}).get("status")!="FAILED",
        "news_ok":n.get("summary",{}).get("data_quality")!="FAILED",
        "critical_news_verified":n.get("guard",{}).get("critical_news_verified",False),
        "market_stale":age>float(config.STALE_MARKET_SECONDS),
        "cooldown":{"active":False},
        "loss_streak_pause":{"active":False},
        "trading_halted":False,
        "asset_already_open":False,
    }
    if asset=="XAU":
        gm=m.get("gold_macro") or {}
        guards.update({
            "xau_session_ok":(not config.XAU_WEEKEND_BLOCK) or now().weekday()<5,
            "gold_macro_ok":gm.get("status") in {"OK","PARTIAL"} and ((gm.get("treasury_yields") or {}).get("status")=="OK"),
            "gold_macro_primary_ok":n.get("guard",{}).get("macro_primary_ok",False) if config.XAU_MACRO_PRIMARY_REQUIRED else True,
        })
    return {
        "status":"READY_FOR_SHADOW" if m.get("status")=="OK" else "FAILED",
        "asset":asset,
        "decision_context":{
            "status":"OK" if m.get("status")=="OK" else "FAILED",
            "asset":asset,
            "generated_at_utc":now().isoformat(),
            "market":m,
            "news":n,
            "guards":guards,
        },
        "guards":guards,
        "account_state":{
            "initial_equity":config.INITIAL_EQUITY,
            "equity":config.INITIAL_EQUITY,
            "daily_pnl":0.0,
            "open_positions":0,
            "current_exposure_usd":0.0,
            "open_assets":[],
            "trading_halted":False,
        },
        "strategy_mode":"SHADOW_LAB",
        "execution_mode":"shadow_only",
    }

def _security_halt(package):
    asset=str(package.get("asset") or "")
    if asset=="XAU":
        return {"halt":False}
    n=(package.get("decision_context") or {}).get("news") or {}
    cutoff=now()-timedelta(hours=float(config.DEFI_SECURITY_HALT_HOURS))
    hits=[]
    for e in n.get("events") or []:
        ts=_parse_ts(e.get("published_at_utc"))
        if ts and ts<cutoff:continue
        txt=(" ".join([str(e.get("title") or ""),str(e.get("summary") or "")])).lower()
        if any(k in txt for k in SECURITY_WORDS):
            hits.append({
                "title":str(e.get("title") or "")[:240],
                "published_at_utc":e.get("published_at_utc"),
                "source":e.get("source"),
            })
    if hits:
        return {"halt":True,"reason":"PROTOCOL_SECURITY_EVENT","events":hits[:5]}
    if not (package.get("guards") or {}).get("critical_news_verified",False):
        return {"halt":True,"reason":"UNVERIFIED_HIGH_IMPACT_NEWS","events":[]}
    return {"halt":False}

def _gold_macro_tags(package):
    m=(package.get("decision_context") or {}).get("market") or {}
    y=((m.get("gold_macro") or {}).get("treasury_yields") or {})
    d=y.get("daily_change_bps") or {}
    tags=[]
    d10=_num(d.get("10y"));d2=_num(d.get("2y"))
    if d10 is not None:
        tags.append("US10Y_UP" if d10>=2 else "US10Y_DOWN" if d10<=-2 else "US10Y_FLAT")
    if d2 is not None:
        tags.append("US2Y_UP" if d2>=2 else "US2Y_DOWN" if d2<=-2 else "US2Y_FLAT")
    curve=_num(y.get("curve_2s10s_bps"))
    if curve is not None:
        tags.append("CURVE_POSITIVE" if curve>=0 else "CURVE_INVERTED")
    return tags

def _lab_eligible(package,group,strategy):
    g=package.get("guards") or {}
    reasons=[]
    if g.get("market_stale") or not g.get("market_ok"):reasons.append("MARKET_DATA_GUARD")
    if not g.get("news_ok"):reasons.append("NEWS_DATA_GUARD")
    if group=="GOLD":
        if not g.get("xau_session_ok",False):reasons.append("XAU_SESSION_BLOCK")
        if not g.get("gold_macro_ok",False):reasons.append("GOLD_MACRO_DATA_GUARD")
        if not g.get("gold_macro_primary_ok",False):reasons.append("GOLD_MACRO_PRIMARY_GUARD")
    else:
        sec=_security_halt(package)
        if sec.get("halt"):reasons.append(sec.get("reason") or "DEFI_SECURITY_HALT")

    spread=adaptive_trainer._spread_pct(package)
    if group=="DEFI" and (spread is None or spread>float(config.DEFI_LAB_MAX_SPREAD_PCT)):
        reasons.append("SPREAD_TOO_WIDE" if spread is not None else "SPREAD_UNAVAILABLE")
    return {"eligible":not reasons,"reasons":reasons,"security":_security_halt(package) if group=="DEFI" else None}

def _candidate_id(group,asset,strategy,direction,candle):
    raw=f"{group}|{asset}|{strategy}|{direction}|{candle}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:18]

def _build_candidate(package,group,strategy):
    asset=package["asset"]
    f5=adaptive_trainer._frame(package,"5m")
    candle=f5.get("last_confirmed_close_time_ms")
    if candle is None:return None

    rows=[]
    for direction in ("LONG","SHORT"):
        score,parts=adaptive_trainer._score(package,direction,strategy)
        q=adaptive_trainer._quality_from_score(score,strategy)
        rows.append((q,score,direction,parts))
    q,score,direction,parts=max(rows,key=lambda x:x[0])
    lv=adaptive_trainer._levels(package,direction,strategy,q)
    if not lv:return None

    market=(package.get("decision_context") or {}).get("market") or {}
    perp=market.get("perp_okx") or {}
    eligible=_lab_eligible(package,group,strategy)
    tags=adaptive_trainer._tags(package,direction,strategy)
    if group=="GOLD":
        tags=sorted(set(tags+_gold_macro_tags(package)+["GOLD"]))
    else:
        tags=sorted(set(tags+["DEFI",asset]))

    horizon=(
        int(config.GOLD_TRAINER_HORIZON_MINUTES)
        if group=="GOLD"
        else int(config.DEFI_LAB_SCALP_HORIZON_MINUTES if strategy=="SCALP" else config.DEFI_LAB_NORMAL_HORIZON_MINUTES)
    )
    c={
        "candidate_id":_candidate_id(group,asset,strategy,direction,candle),
        "created_at_utc":now().isoformat(),
        "group":group,
        "asset":asset,
        "candle_id":candle,
        "strategy":strategy,
        "direction":direction,
        "base_score":round(score,3),
        "base_quality":round(q,2),
        "quality":round(q,2),
        "components":parts,
        "tags":tags,
        "market_regime":adaptive_trainer._market_regime(package),
        "spread_pct":adaptive_trainer._spread_pct(package),
        "funding_rate":_num(perp.get("funding_rate")),
        "shadow_eligible":bool(eligible.get("eligible")),
        "eligibility_reasons":eligible.get("reasons") or [],
        "security":eligible.get("security"),
        "time_horizon_minutes":horizon,
        **lv,
    }
    c=adaptive_trainer._apply_cost_aware_geometry(c)
    return c

def _similar_stats(candidate,outcomes):
    tags=set(candidate.get("tags") or [])
    num=0.0;den=0.0;samples=0
    for x in outcomes:
        if x.get("group")!=candidate.get("group"):continue
        if x.get("asset")!=candidate.get("asset"):continue
        if x.get("strategy")!=candidate.get("strategy"):continue
        if candidate.get("geometry_version") and x.get("geometry_version")!=candidate.get("geometry_version"):continue
        r=_num(x.get("net_r") if x.get("net_r") is not None else x.get("r_result"))
        if r is None:continue
        weight=1.0
        if x.get("direction")==candidate.get("direction"):weight+=1.0
        if x.get("market_regime") and x.get("market_regime")==candidate.get("market_regime"):
            weight+=1.5
        elif x.get("market_regime") and candidate.get("market_regime"):
            weight*=0.65
        xt=set(x.get("tags") or [])
        union=len(tags|xt);inter=len(tags&xt)
        if union:weight+=2.0*(inter/union)
        num+=weight*r;den+=weight;samples+=1
    avg=(num/den) if den else 0.0
    prior=float(config.ADAPTIVE_TRAINER_LEARNING_PRIOR_SAMPLES)
    shrink=samples/(samples+prior)
    adj=_clamp(avg*shrink*float(config.ADAPTIVE_TRAINER_R_TO_QUALITY_MULT),-8,8)
    return {"samples":samples,"avg_net_r":round(avg,4),"adjustment":round(adj,2)}

def _record(candidates):
    existing={x.get("candidate_id") for x in _read(CANDIDATES)[-3000:]}
    n=0
    for c in candidates:
        if not c or not c.get("shadow_eligible") or not c.get("cost_efficient"):continue
        threshold=float(config.GOLD_TRAINER_SHADOW_MIN_QUALITY if c.get("group")=="GOLD" else config.DEFI_LAB_SHADOW_MIN_QUALITY)
        if float(c.get("base_quality") or 0)<threshold:continue
        if c.get("candidate_id") in existing:continue
        _append(CANDIDATES,c);existing.add(c.get("candidate_id"));n+=1
    return n

def evaluate_due(batch=None):
    candidates=_read(CANDIDATES)
    outcomes=_read(OUTCOMES)
    done={x.get("candidate_id") for x in outcomes}
    pending=[]
    utc=now();limit=int(batch or config.MULTI_MARKET_TRAINER_OUTCOME_BATCH)
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
        cfg=ASSETS.get(asset) or {}
        inst=cfg.get("okx_swap")
        if not inst:continue
        if asset not in bars_cache:
            try:bars_cache[asset]=market_snapshot._okx_confirmed_candles(inst,"5m",300)
            except Exception:bars_cache[asset]=[]
        start=int(dt.timestamp()*1000);end=int((dt+timedelta(minutes=horizon)).timestamp()*1000)
        bars=[b for b in bars_cache[asset] if start<=int(b.get("open_time_ms",0))<=end]
        if not bars:continue
        label,gross=adaptive_trainer._path(c,bars)
        cost=adaptive_trainer._estimated_cost(c)
        gross=float(gross or 0.0)
        net=gross-float(cost.get("cost_r") or 0.0)
        row={
            "evaluated_at_utc":now().isoformat(),
            "candidate_id":c.get("candidate_id"),
            "created_at_utc":c.get("created_at_utc"),
            "group":c.get("group"),
            "asset":asset,
            "strategy":c.get("strategy"),
            "direction":c.get("direction"),
            "market_regime":c.get("market_regime"),
            "geometry_version":c.get("geometry_version"),
            "tags":c.get("tags") or [],
            "label":label,
            "gross_r":round(gross,4),
            "estimated_cost_r":round(float(cost.get("cost_r") or 0.0),4),
            "estimated_cost_pct":round(float(cost.get("total_pct") or 0.0),4),
            "net_r":round(net,4),
            "r_result":round(net,4),
            "horizon_minutes":horizon,
        }
        _append(OUTCOMES,row);done.add(c.get("candidate_id"));added+=1
    return {"status":"OK","evaluated":added}

def _scan_gold(outcomes):
    if not config.GOLD_TRAINER_ENABLED:return {"status":"DISABLED","recorded":0}
    p=_package("XAU")
    c=_build_candidate(p,"GOLD","NORMAL")
    if c:
        st=_similar_stats(c,outcomes);c["learning"]=st
        c["quality"]=round(_clamp(float(c["base_quality"])+float(st["adjustment"])),2)
    n=_record([c] if c else [])
    return {"status":"OK","recorded":n,"candidate":c}

def _scan_defi(outcomes):
    if not config.DEFI_TRAINER_ENABLED:return {"status":"DISABLED","recorded":0,"universe":{}}
    u=defi_universe.summary()
    candidates=[]
    errors=[]
    for asset in u.get("selected_assets") or []:
        try:
            p=_package(asset)
            for strategy in ("SCALP","NORMAL"):
                c=_build_candidate(p,"DEFI",strategy)
                if c:
                    st=_similar_stats(c,outcomes);c["learning"]=st
                    c["quality"]=round(_clamp(float(c["base_quality"])+float(st["adjustment"])),2)
                    candidates.append(c)
        except Exception as e:
            errors.append({"asset":asset,"error":str(e)})
    n=_record(candidates)
    candidates.sort(key=lambda x:float(x.get("quality") or 0),reverse=True)
    return {
        "status":"OK" if not errors else "PARTIAL",
        "recorded":n,
        "universe":u,
        "best":candidates[0] if candidates else None,
        "candidates":candidates[:10],
        "errors":errors,
    }

def run_once(force=False):
    st=_state()
    evaluated=evaluate_due()
    outcomes=_read(OUTCOMES)
    result={"evaluated":evaluated.get("evaluated",0)}

    gold_due=force or _due(st.get("last_gold_scan_utc"),config.GOLD_TRAINER_INTERVAL_MINUTES)
    defi_due=force or _due(st.get("last_defi_scan_utc"),config.DEFI_LAB_SCAN_MINUTES)

    if gold_due:
        result["gold"]=_scan_gold(outcomes)
        st["last_gold_scan_utc"]=now().isoformat()
    if defi_due:
        result["defi"]=_scan_defi(outcomes)
        st["last_defi_scan_utc"]=now().isoformat()
        st["last_universe"]=(result.get("defi") or {}).get("universe")

    st["last_run_utc"]=now().isoformat()
    st["last_result"]={
        "evaluated":result.get("evaluated"),
        "gold":{k:v for k,v in (result.get("gold") or {}).items() if k!="candidate"},
        "defi":{k:v for k,v in (result.get("defi") or {}).items() if k not in {"candidates","best","universe"}},
    }
    _save_state(st)
    STATE.update({
        "status":"OK","last_error":None,"last_run_utc":st.get("last_run_utc"),
        "last_gold_scan_utc":st.get("last_gold_scan_utc"),
        "last_defi_scan_utc":st.get("last_defi_scan_utc"),
        "last_universe":st.get("last_universe"),
        "last_result":st.get("last_result"),
    })
    return result

def run_forever():
    while True:
        try:
            run_once(False)
        except Exception as e:
            STATE.update({"status":"DEGRADED","last_error":str(e),"last_run_utc":now().isoformat()})
        time.sleep(max(15,int(config.MULTI_MARKET_TRAINER_TICK_SECONDS)))

def summary(hours=168):
    cutoff=now()-timedelta(hours=float(hours))
    all_outcomes=[x for x in _read(OUTCOMES) if (_parse_ts(x.get("evaluated_at_utc")) or datetime.min.replace(tzinfo=timezone.utc))>=cutoff]
    all_candidates=[x for x in _read(CANDIDATES) if (_parse_ts(x.get("created_at_utc")) or datetime.min.replace(tzinfo=timezone.utc))>=cutoff]
    outcomes=[x for x in all_outcomes if x.get("geometry_version")==config.TRAINER_GEOMETRY_VERSION]
    candidates=[x for x in all_candidates if x.get("geometry_version")==config.TRAINER_GEOMETRY_VERSION]
    by_group=defaultdict(lambda:{"shadow":0,"evaluated":0,"net":0.0,"gross":0.0,"cost":0.0})
    by_asset=defaultdict(lambda:{"n":0,"net":0.0})
    labels=defaultdict(Counter)
    for c in candidates:
        by_group[str(c.get("group") or "UNKNOWN")]["shadow"]+=1
    for x in outcomes:
        g=str(x.get("group") or "UNKNOWN")
        net=float(x.get("net_r") if x.get("net_r") is not None else x.get("r_result") or 0)
        gross=float(x.get("gross_r") if x.get("gross_r") is not None else net)
        cost=float(x.get("estimated_cost_r") or 0)
        by_group[g]["evaluated"]+=1;by_group[g]["net"]+=net;by_group[g]["gross"]+=gross;by_group[g]["cost"]+=cost
        a=str(x.get("asset") or "UNKNOWN")
        by_asset[a]["n"]+=1;by_asset[a]["net"]+=net
        labels[g][str(x.get("label") or "UNKNOWN")]+=1

    def finish_group(v):
        n=v["evaluated"]
        return {
            "shadow":v["shadow"],"evaluated":n,
            "avg_net_r":round(v["net"]/n,3) if n else 0.0,
            "avg_gross_r":round(v["gross"]/n,3) if n else 0.0,
            "avg_cost_r":round(v["cost"]/n,3) if n else 0.0,
        }
    groups={k:finish_group(v) for k,v in by_group.items()}
    assets={k:{"samples":v["n"],"avg_net_r":round(v["net"]/v["n"],3) if v["n"] else 0.0} for k,v in by_asset.items()}
    state=_state()
    return {
        "hours":float(hours),
        "geometry_version":config.TRAINER_GEOMETRY_VERSION,
        "legacy_shadow_candidates":len(all_candidates)-len(candidates),
        "legacy_evaluated":len(all_outcomes)-len(outcomes),
        "groups":groups,
        "assets":assets,
        "labels":{k:dict(v) for k,v in labels.items()},
        "defi_universe":state.get("last_universe") or defi_universe.cached_summary(),
        "runtime":{
            "status":STATE.get("status"),
            "last_error":STATE.get("last_error"),
            "last_gold_scan_utc":state.get("last_gold_scan_utc"),
            "last_defi_scan_utc":state.get("last_defi_scan_utc"),
        },
    }

def gold_text(hours=168):
    s=summary(hours)
    g=(s.get("groups") or {}).get("GOLD",{})
    labels=(s.get("labels") or {}).get("GOLD",{})
    x=(s.get("assets") or {}).get("XAU",{})
    return "\n".join([
        f"🥇 <b>GOLD TRAINER — {int(float(hours))}h</b>","",
        f"Shadow: <b>{g.get('shadow',0)}</b>",
        f"Evaluated: <b>{g.get('evaluated',0)}</b>",
        f"XAU NET R: <b>{x.get('avg_net_r',g.get('avg_net_r',0)):.3f}R</b>",
        f"Gross / friction: <b>{g.get('avg_gross_r',0):.3f}R / {g.get('avg_cost_r',0):.3f}R</b>",
        f"TP2: <b>{labels.get('TP2_HIT',0)}</b> | Stops: <b>{labels.get('STOP_HIT',0)}</b>","",
        "Gold сейчас shadow-only в Trainer v3: наблюдает XAU, macro/yields и новости, но из AUTO ордера не открывает.",
    ])

def defi_text(hours=168):
    s=summary(hours)
    g=(s.get("groups") or {}).get("DEFI",{})
    u=s.get("defi_universe") or {}
    lines=[
        f"🟣 <b>DEFI TRAINER — {int(float(hours))}h</b>","",
        "Dynamic universe: <b>"+(", ".join(u.get("selected_assets") or []) or "—")+"</b>",
        f"Shadow: <b>{g.get('shadow',0)}</b> | Evaluated: <b>{g.get('evaluated',0)}</b>",
        f"NET R: <b>{g.get('avg_net_r',0):.3f}R</b> | Friction: <b>{g.get('avg_cost_r',0):.3f}R</b>","",
        "<b>By asset:</b>",
    ]
    shown=0
    for a,v in sorted((s.get("assets") or {}).items()):
        if a in set(config.DEFI_LAB_WATCHLIST):
            lines.append(f"• {a}: {v.get('samples',0)} | {v.get('avg_net_r',0):.3f}R");shown+=1
    if not shown:lines.append("• пока недостаточно оценённых исходов")
    lines += ["","DeFi сейчас shadow-only. Protocol security events блокируют новые тренировочные кандидаты."]
    return "\n".join(lines)

def telegram_text(hours=168):
    s=summary(hours)
    gold=(s.get("groups") or {}).get("GOLD",{})
    defi=(s.get("groups") or {}).get("DEFI",{})
    u=s.get("defi_universe") or {}
    lines=[
        f"🌐 <b>MULTI-MARKET LAB v4 — {int(float(hours))}h</b>","",
        f"Geometry: <b>{s.get('geometry_version')}</b>",
        "🥇 <b>GOLD TRAINER</b>",
        f"Shadow: <b>{gold.get('shadow',0)}</b> | Evaluated: <b>{gold.get('evaluated',0)}</b>",
        f"NET R: <b>{gold.get('avg_net_r',0):.3f}R</b> | Friction: <b>{gold.get('avg_cost_r',0):.3f}R</b>","",
        "🟣 <b>DEFI TRAINER</b>",
        "Universe: <b>"+(", ".join(u.get("selected_assets") or []) or "—")+"</b>",
        f"Shadow: <b>{defi.get('shadow',0)}</b> | Evaluated: <b>{defi.get('evaluated',0)}</b>",
        f"NET R: <b>{defi.get('avg_net_r',0):.3f}R</b> | Friction: <b>{defi.get('avg_cost_r',0):.3f}R</b>","",
        "<b>DeFi by asset:</b>",
    ]
    defi_assets=set(config.DEFI_LAB_WATCHLIST)
    shown=0
    for a,v in sorted((s.get("assets") or {}).items()):
        if a in defi_assets:
            lines.append(f"• {a}: {v.get('samples',0)} | {v.get('avg_net_r',0):.3f}R");shown+=1
    if not shown:lines.append("• пока недостаточно оценённых исходов")
    lines += [
        "",
        "Gold и DeFi здесь только обучаются: ордера не открываются.",
        "v4 считает только новую cost-aware геометрию; старая статистика сохранена отдельно.",
        "NET R учитывает оценку fees + spread + slippage + funding.",
    ]
    return "\n".join(lines)

if __name__=="__main__":
    print(json.dumps(summary(),ensure_ascii=False,indent=2))

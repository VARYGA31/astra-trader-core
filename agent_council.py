#!/usr/bin/env python3
"""ASTRA Shadow Agent Council v1.

Six deterministic, zero-token specialist agents inspect the SAME package already
built for the live strategy. Their vote is recorded for research and visualized
in Mission Control, but it has no authority over model calls, Risk Engine,
position sizing, leverage, execution, or runtime mode.

This is deliberately an evidence layer first. If later OOS data proves that the
Council improves NET expectancy, a separate reviewed change can promote selected
signals into the live deterministic gate.
"""
import json
import math
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import config
import decision_gate
import market_scanner

ORDER_CAPABILITY=False
MODEL_CALL_CAPABILITY=False
EXECUTION_AUTHORITY=False

LOCK=threading.RLock()
LOG=Path(config.STATE_DIR)/"shadow_agent_council.jsonl"
OUTCOMES=Path(config.STATE_DIR)/"shadow_agent_council_outcomes.jsonl"
STATE=Path(config.STATE_DIR)/"shadow_agent_council_state.json"

AGENT_META={
    "NOVA":{"role":"Trend / structure","icon":"↗"},
    "ORION":{"role":"Momentum / timing","icon":"⚡"},
    "VEGA":{"role":"Order flow / scanner","icon":"◉"},
    "ATLAS":{"role":"Derivatives / crowding","icon":"⌁"},
    "CERBERUS":{"role":"Anti-FOMO / risk veto","icon":"◆"},
    "HELIOS":{"role":"Macro / news context","icon":"☼"},
}

def _now():
    return datetime.now(timezone.utc)

def _num(x,default=None):
    try:return float(x)
    except Exception:return default

def _frame(market,tf):
    return (((market or {}).get("multi_timeframe") or {}).get("frames") or {}).get(tf) or {}

def _vote(name,vote,confidence,reason,veto=False,details=None):
    vote=str(vote or "NEUTRAL").upper()
    if vote not in {"LONG","SHORT","NEUTRAL"}:vote="NEUTRAL"
    return {
        "agent":name,
        "role":AGENT_META[name]["role"],
        "icon":AGENT_META[name]["icon"],
        "vote":vote,
        "confidence":round(max(0.0,min(100.0,float(confidence or 0.0))),2),
        "reason":str(reason or "")[:240],
        "veto":bool(veto),
        "details":details or {},
    }

def _trend_agent(package,gate):
    market=((package.get("decision_context") or {}).get("market") or {})
    frames=(market.get("multi_timeframe") or {}).get("frames") or {}
    labels=["4h","1h","15m"] if str(package.get("strategy_mode") or "NORMAL").upper()=="NORMAL" else ["5m","3m","1m"]
    bull=bear=0
    seen=0
    for tf in labels:
        r=(frames.get(tf) or {}).get("regimes") or {}
        t=str(r.get("trend") or r.get("structure") or "").upper()
        if "BULL" in t:bull+=1
        elif "BEAR" in t:bear+=1
        if t:seen+=1
    direction=str((gate or {}).get("allowed_direction") or ((gate or {}).get("mtf") or {}).get("direction") or "").upper()
    if direction in {"LONG","SHORT"}:
        quality=_num((gate or {}).get("mtf_quality"),_num(((gate or {}).get("mtf") or {}).get("quality"),65.0))
        return _vote("NOVA",direction,max(55.0,quality or 55.0),"Deterministic MTF direction",details={"bull_frames":bull,"bear_frames":bear})
    if bull>bear and bull>=2:return _vote("NOVA","LONG",65+8*(bull-2),"Majority bullish timeframe regime",details={"bull_frames":bull,"bear_frames":bear})
    if bear>bull and bear>=2:return _vote("NOVA","SHORT",65+8*(bear-2),"Majority bearish timeframe regime",details={"bull_frames":bull,"bear_frames":bear})
    return _vote("NOVA","NEUTRAL",35,"No stable multi-timeframe direction",details={"bull_frames":bull,"bear_frames":bear,"seen":seen})

def _momentum_agent(package):
    market=((package.get("decision_context") or {}).get("market") or {})
    spot=market.get("spot") or {}
    ch=spot.get("changes_pct") or {}
    ind=spot.get("indicators") or {}
    rsi=_num(ind.get("rsi14"),50.0)
    one=_num(ch.get("1h"),0.0) or 0.0
    four=_num(ch.get("4h"),0.0) or 0.0
    score=0.0
    score+=1.0 if one>=0.25 else -1.0 if one<=-0.25 else 0.0
    score+=1.0 if four>=0.60 else -1.0 if four<=-0.60 else 0.0
    score+=1.0 if 55<=rsi<70 else -1.0 if 30<rsi<=45 else 0.0
    extreme=(rsi>=75 or rsi<=25)
    if score>=1:
        return _vote("ORION","LONG",min(88,55+abs(score)*10- (10 if extreme else 0)),"Positive momentum stack",details={"rsi14":rsi,"change_1h_pct":one,"change_4h_pct":four,"extreme":extreme})
    if score<=-1:
        return _vote("ORION","SHORT",min(88,55+abs(score)*10- (10 if extreme else 0)),"Negative momentum stack",details={"rsi14":rsi,"change_1h_pct":one,"change_4h_pct":four,"extreme":extreme})
    return _vote("ORION","NEUTRAL",40,"Momentum is mixed",details={"rsi14":rsi,"change_1h_pct":one,"change_4h_pct":four})

def _vega_agent(package):
    market=((package.get("decision_context") or {}).get("market") or {})
    spot=market.get("spot") or {}
    imb=_num((spot.get("order_book") or {}).get("imbalance"),0.0) or 0.0
    ratio=_num((spot.get("trade_flow") or {}).get("buy_sell_ratio"))
    score=0.0
    if imb>=0.12:score+=1.0
    elif imb<=-0.12:score-=1.0
    if ratio is not None:
        if ratio>=1.15:score+=1.0
        elif ratio<=0.87:score-=1.0

    scan=market_scanner.summary()
    asset=str(package.get("asset") or "").upper()
    rank=None;opp=None
    for i,row in enumerate(scan.get("ranking") or [],1):
        if row.get("asset")==asset:
            rank=i;opp=_num(row.get("opportunity_score"));break
    bonus=10 if rank==1 else 6 if rank in {2,3} else 0
    if score>0:return _vote("VEGA","LONG",min(90,58+12*abs(score)+bonus),"Buy-side order flow / scanner activity",details={"imbalance":imb,"buy_sell_ratio":ratio,"scanner_rank":rank,"opportunity_score":opp})
    if score<0:return _vote("VEGA","SHORT",min(90,58+12*abs(score)+bonus),"Sell-side order flow / scanner activity",details={"imbalance":imb,"buy_sell_ratio":ratio,"scanner_rank":rank,"opportunity_score":opp})
    return _vote("VEGA","NEUTRAL",45+bonus,"Order flow is balanced",details={"imbalance":imb,"buy_sell_ratio":ratio,"scanner_rank":rank,"opportunity_score":opp})

def _atlas_agent(package,target_hint=None):
    market=((package.get("decision_context") or {}).get("market") or {})
    perp=market.get("perp_okx") or {}
    funding=_num(perp.get("funding_rate"))
    oi=_num(perp.get("open_interest_contracts"))
    bid=_num(perp.get("bid_price"));ask=_num(perp.get("ask_price"))
    spread=None
    if bid and ask and ask>=bid:
        spread=(ask-bid)/((ask+bid)/2.0)*100.0
    # Funding is a crowding modifier, not a standalone directional oracle.
    if funding is None:
        return _vote("ATLAS","NEUTRAL",35,"Funding unavailable",details={"open_interest_contracts":oi,"spread_pct":spread})
    extreme=abs(funding)>=0.0005
    if extreme and funding>0:
        return _vote("ATLAS","SHORT",62,"Positive funding suggests crowded longs",details={"funding_rate":funding,"open_interest_contracts":oi,"spread_pct":spread})
    if extreme and funding<0:
        return _vote("ATLAS","LONG",62,"Negative funding suggests crowded shorts",details={"funding_rate":funding,"open_interest_contracts":oi,"spread_pct":spread})
    return _vote("ATLAS","NEUTRAL",48,"Funding not extreme",details={"funding_rate":funding,"open_interest_contracts":oi,"spread_pct":spread})

def _cerberus_agent(package,target_hint=None):
    g=package.get("guards") or {}
    hard=[
        "market_stale" if g.get("market_stale") else None,
        "market_not_ok" if not g.get("market_ok",True) else None,
        "news_not_ok" if not g.get("news_ok",True) else None,
        "trading_halted" if g.get("trading_halted") else None,
        "cooldown" if (g.get("cooldown") or {}).get("active") else None,
        "loss_streak_pause" if (g.get("loss_streak_pause") or {}).get("active") else None,
    ]
    hard=[x for x in hard if x]
    if hard:
        return _vote("CERBERUS","NEUTRAL",95,"Hard safety guard active",veto=True,details={"guards":hard})
    if target_hint in {"LONG","SHORT"}:
        chase=decision_gate.entry_guard(package,target_hint)
        if chase.get("blocked"):
            return _vote("CERBERUS","NEUTRAL",95,chase.get("reason") or "Anti-FOMO chase risk",veto=True,details=chase)
        return _vote("CERBERUS",target_hint,70,"No anti-chase veto",details=chase)
    return _vote("CERBERUS","NEUTRAL",55,"No target direction yet; safety clear")

def _helios_agent(package,target_hint=None):
    asset=str(package.get("asset") or "").upper()
    dc=package.get("decision_context") or {}
    market=dc.get("market") or {}
    news=dc.get("news") or {}
    high=[e for e in (news.get("events") or []) if e.get("impact_hint")=="HIGH" and e.get("trade_usable")]
    if asset=="XAU":
        gm=market.get("gold_macro") or {}
        if str(gm.get("status") or "").upper()=="FAILED":
            return _vote("HELIOS","NEUTRAL",95,"Gold macro data failed",veto=True,details={"gold_macro_status":gm.get("status")})
        if high:
            return _vote("HELIOS","NEUTRAL",85,"Fresh high-impact macro context requires caution",veto=True,details={"high_impact_events":len(high)})
        if target_hint in {"LONG","SHORT"}:
            return _vote("HELIOS",target_hint,68,"Gold macro/news layer has no veto",details={"gold_macro_status":gm.get("status"),"high_impact_events":0})
    else:
        # For crypto, verified HIGH news is context. Only veto if the package's
        # deterministic news guard itself is not healthy.
        ng=news.get("guard") or {}
        if str(ng.get("status") or "").upper() in {"BLOCK","FAILED"}:
            return _vote("HELIOS","NEUTRAL",90,"News guard blocks the setup",veto=True,details={"news_guard":ng})
        if target_hint in {"LONG","SHORT"}:
            return _vote("HELIOS",target_hint,58 if high else 64,"No macro/news veto",details={"high_impact_events":len(high)})
    return _vote("HELIOS","NEUTRAL",45,"No directional macro/news edge",details={"high_impact_events":len(high)})

def evaluate(package,gate=None):
    if not config.SHADOW_AGENT_COUNCIL_ENABLED:
        return {"status":"DISABLED","order_capability":False,"model_call_capability":False,"execution_authority":False}
    package=package or {};gate=gate or {}
    asset=str(package.get("asset") or "").upper()
    target=str(gate.get("allowed_direction") or (gate.get("mtf") or {}).get("direction") or "").upper()
    if target not in {"LONG","SHORT"}:target=None

    nova=_trend_agent(package,gate)
    if not target and nova.get("vote") in {"LONG","SHORT"}:
        target=nova["vote"]
    agents=[
        nova,
        _momentum_agent(package),
        _vega_agent(package),
        _atlas_agent(package,target),
        _cerberus_agent(package,target),
        _helios_agent(package,target),
    ]

    if not target:
        long_w=sum(a["confidence"] for a in agents if a["vote"]=="LONG")
        short_w=sum(a["confidence"] for a in agents if a["vote"]=="SHORT")
        if long_w>short_w*1.15:target="LONG"
        elif short_w>long_w*1.15:target="SHORT"

    agree=[a for a in agents if target and a["vote"]==target]
    oppose=[a for a in agents if target and a["vote"] in {"LONG","SHORT"} and a["vote"]!=target]
    neutral=[a for a in agents if a["vote"]=="NEUTRAL"]
    vetoes=[a for a in agents if a.get("veto")]

    support=sum(a["confidence"]/100.0 for a in agree)
    opposition=sum(a["confidence"]/100.0 for a in oppose)
    directional=support+opposition
    support_ratio=(support/directional) if directional>0 else 0.0
    mtf_quality=_num(gate.get("mtf_quality"),_num((gate.get("mtf") or {}).get("quality")))
    score=100.0*support_ratio if target else 0.0
    if mtf_quality is not None and target:
        score=0.78*score+0.22*max(0.0,min(100.0,mtf_quality))
    score=max(0.0,min(100.0,score))

    if vetoes:
        status="VETO"
    elif not target:
        status="NO_DIRECTION"
    elif len(agree)>=int(config.SHADOW_AGENT_COUNCIL_MIN_AGREE) and score>=float(config.SHADOW_AGENT_COUNCIL_STRONG_SCORE):
        status="STRONG_CONSENSUS"
    elif len(agree)>=3 and score>=60:
        status="CONSENSUS"
    else:
        status="MIXED"

    return {
        "status":status,
        "generated_at_utc":_now().isoformat(),
        "asset":asset,
        "strategy_mode":str(package.get("strategy_mode") or "NORMAL").upper(),
        "target_direction":target,
        "council_score":round(score,2),
        "agree_count":len(agree),
        "oppose_count":len(oppose),
        "neutral_count":len(neutral),
        "veto_count":len(vetoes),
        "support_ratio":round(support_ratio,4),
        "mtf_quality":mtf_quality,
        "gate_reason":gate.get("reason"),
        "agents":agents,
        "shadow_candidate":bool(status=="STRONG_CONSENSUS"),
        "order_capability":False,
        "model_call_capability":False,
        "execution_authority":False,
        "note":"Shadow evidence only; never used by execution in v1.",
    }

def _load_state():
    try:
        x=json.loads(STATE.read_text(encoding="utf-8"))
        return x if isinstance(x,dict) else {}
    except Exception:return {}

def _append_jsonl(path,row):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("a",encoding="utf-8") as f:
        f.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")

def _read_jsonl(path,limit=5000):
    rows=[]
    try:
        with path.open("r",encoding="utf-8") as f:
            for line in f:
                try:
                    x=json.loads(line)
                    if isinstance(x,dict):rows.append(x)
                except Exception:
                    continue
    except Exception:
        pass
    return rows[-max(1,int(limit)):]

def _reference_price(package):
    market=((package or {}).get("decision_context") or {}).get("market") or {}
    spot=market.get("spot") or {}
    perp=market.get("perp_okx") or {}
    return _num(spot.get("price") or perp.get("last_price"))

def _eval_minutes(mode):
    return int(config.SHADOW_AGENT_COUNCIL_MICRO_EVAL_MINUTES) if str(mode or "").upper()=="MICRO" else int(config.SHADOW_AGENT_COUNCIL_NORMAL_EVAL_MINUTES)

def _settle_pending(st,asset,current_price):
    if current_price is None or current_price<=0:
        return 0
    now=_now()
    pending=list(st.get("pending") or [])
    keep=[];done=0
    for x in pending:
        if str(x.get("asset") or "").upper()!=asset:
            keep.append(x);continue
        try:
            due=datetime.fromisoformat(str(x.get("due_at_utc") or "").replace("Z","+00:00"))
        except Exception:
            due=None
        if due is None or due>now:
            keep.append(x);continue
        entry=_num(x.get("reference_price"))
        direction=str(x.get("target_direction") or "").upper()
        if not entry or direction not in {"LONG","SHORT"}:
            continue
        raw=(current_price-entry)/entry*100.0
        signed=raw if direction=="LONG" else -raw
        out={
            **x,
            "evaluated_at_utc":now.isoformat(),
            "exit_reference_price":current_price,
            "raw_return_pct":round(raw,6),
            "directional_return_pct":round(signed,6),
            "directional_hit":bool(signed>0),
        }
        _append_jsonl(OUTCOMES,out);done+=1
    st["pending"]=keep[-max(1,int(config.SHADOW_AGENT_COUNCIL_MAX_PENDING)):]
    st["evaluated_total"]=int(st.get("evaluated_total",0))+done
    return done

def _save_state(x):
    STATE.parent.mkdir(parents=True,exist_ok=True)
    tmp=STATE.with_name(f"{STATE.name}.{threading.get_ident()}.{int(_now().timestamp()*1_000_000)}.tmp")
    tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding="utf-8")
    tmp.replace(STATE)

def record(result,package=None):
    if not config.SHADOW_AGENT_COUNCIL_ENABLED or not isinstance(result,dict):
        return {"status":"DISABLED"}
    asset=str(result.get("asset") or "").upper()
    if not asset:return {"status":"IGNORED","reason":"NO_ASSET"}
    current_price=_reference_price(package)
    with LOCK:
        st=_load_state()
        settled=_settle_pending(st,asset,current_price)

        old=(st.get("latest_by_asset") or {}).get(asset) or {}
        try:
            old_ts=datetime.fromisoformat(str(old.get("generated_at_utc") or "").replace("Z","+00:00"))
            age=(_now()-old_ts).total_seconds()
        except Exception:
            age=999999
        deduped=age<float(config.SHADOW_AGENT_COUNCIL_RECORD_MIN_SECONDS) and old.get("status")==result.get("status") and old.get("target_direction")==result.get("target_direction")
        st.setdefault("latest_by_asset",{})[asset]=result

        if not deduped:
            _append_jsonl(LOG,result)
            st["last"]=result
            st["recorded_total"]=int(st.get("recorded_total",0))+1
            counts=st.setdefault("status_counts",{})
            k=str(result.get("status") or "UNKNOWN")
            counts[k]=int(counts.get(k,0))+1

            direction=str(result.get("target_direction") or "").upper()
            if current_price and current_price>0 and direction in {"LONG","SHORT"}:
                mode=str(result.get("strategy_mode") or "NORMAL").upper()
                created=_now()
                mins=max(1,_eval_minutes(mode))
                candidate={
                    "candidate_id":f"{asset}:{int(created.timestamp())}:{st['recorded_total']}",
                    "created_at_utc":created.isoformat(),
                    "due_at_utc":datetime.fromtimestamp(created.timestamp()+mins*60,tz=timezone.utc).isoformat(),
                    "horizon_minutes":mins,
                    "asset":asset,
                    "strategy_mode":mode,
                    "council_status":result.get("status"),
                    "council_score":result.get("council_score"),
                    "agree_count":result.get("agree_count"),
                    "oppose_count":result.get("oppose_count"),
                    "veto_count":result.get("veto_count"),
                    "target_direction":direction,
                    "reference_price":current_price,
                    "shadow_candidate":bool(result.get("shadow_candidate")),
                }
                st.setdefault("pending",[]).append(candidate)
                st["pending"]=st["pending"][-max(1,int(config.SHADOW_AGENT_COUNCIL_MAX_PENDING)):]

        _save_state(st)
        return {"status":"DEDUPED" if deduped else "OK","settled":settled}

def summary():
    if not config.SHADOW_AGENT_COUNCIL_ENABLED:
        return {"status":"DISABLED","order_capability":False,"model_call_capability":False,"execution_authority":False}
    with LOCK:
        st=_load_state()
    latest=st.get("latest_by_asset") or {}
    strong=[x for x in latest.values() if isinstance(x,dict) and x.get("status")=="STRONG_CONSENSUS"]
    outcomes=_read_jsonl(OUTCOMES,5000)
    by_status={}
    for x in outcomes:
        k=str(x.get("council_status") or "UNKNOWN")
        d=by_status.setdefault(k,{"samples":0,"hits":0,"sum_directional_return_pct":0.0})
        d["samples"]+=1
        d["hits"]+=1 if x.get("directional_hit") else 0
        d["sum_directional_return_pct"]+=float(x.get("directional_return_pct") or 0.0)
    for d in by_status.values():
        n=d["samples"]
        d["hit_rate_pct"]=round(100.0*d["hits"]/n,2) if n else 0.0
        d["avg_directional_return_pct"]=round(d["sum_directional_return_pct"]/n,5) if n else 0.0
        d.pop("sum_directional_return_pct",None)
    return {
        "status":"OK",
        "recorded_total":int(st.get("recorded_total",0)),
        "evaluated_total":len(outcomes),
        "pending_total":len(st.get("pending") or []),
        "status_counts":st.get("status_counts") or {},
        "outcome_metrics_by_status":by_status,
        "recent_outcomes":outcomes[-20:],
        "last":st.get("last"),
        "latest_by_asset":latest,
        "strong_assets":[x.get("asset") for x in strong],
        "agent_meta":AGENT_META,
        "order_capability":False,
        "model_call_capability":False,
        "execution_authority":False,
        "outcome_note":"Forward directional-return proxy only; not trade PnL or proof of edge.",
    }

if __name__=="__main__":
    print(json.dumps(summary(),ensure_ascii=False,indent=2))

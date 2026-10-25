#!/usr/bin/env python3
"""ASTRA Alpha Factory v1 — shadow-only empirical strategy discovery.

The factory mines already-evaluated Adaptive Trainer outcomes for repeatable
combinations of market features ("genes"). Every genome is evaluated
chronologically with train/OOS separation, walk-forward stability, costs already
embedded in NET-R, drawdown, profit factor, Spearman IC and decay detection.

It has deliberately NO model or order capability. A SHADOW_CHAMPION is research
evidence only and can never reach execution from this module.
"""
import hashlib
import itertools
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import config
import adaptive_trainer

ORDER_CAPABILITY=False
MODEL_CALL_CAPABILITY=False

DIR=Path(config.STATE_DIR)
SNAPSHOT=DIR/"alpha_factory_snapshot.json"

_EXCLUDED_TAGS={
    "LONG","SHORT","NORMAL","SCALP",
}
_ALLOWED_PREFIXES=(
    "4H_","1H_","15M_","5M_","3M_","1M_",
    "VOL_","SPREAD_","RSI_",
)
_ALLOWED_EXACT={
    "BREAKOUT","COST_AWARE_V4",
}

def _now():
    return datetime.now(timezone.utc)

def _parse_ts(x):
    try:
        return datetime.fromisoformat(str(x or "").replace("Z","+00:00"))
    except Exception:
        return None

def _num(x,default=None):
    try:return float(x)
    except Exception:return default

def _read_jsonl(path):
    out=[]
    try:
        with Path(path).open("r",encoding="utf-8") as f:
            for line in f:
                try:
                    row=json.loads(line)
                    if isinstance(row,dict):out.append(row)
                except Exception:
                    continue
    except Exception:
        pass
    return out

def _atomic_json(path,payload):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    tmp.replace(path)

def _rankdata(values):
    pairs=sorted(enumerate(values),key=lambda x:x[1])
    ranks=[0.0]*len(values)
    i=0
    while i<len(pairs):
        j=i+1
        while j<len(pairs) and pairs[j][1]==pairs[i][1]:
            j+=1
        rank=(i+j-1)/2.0+1.0
        for k in range(i,j):
            ranks[pairs[k][0]]=rank
        i=j
    return ranks

def _spearman(xs,ys):
    if len(xs)!=len(ys) or len(xs)<3:
        return None
    rx=_rankdata(xs); ry=_rankdata(ys)
    mx=sum(rx)/len(rx); my=sum(ry)/len(ry)
    num=sum((a-mx)*(b-my) for a,b in zip(rx,ry))
    dx=math.sqrt(sum((a-mx)**2 for a in rx))
    dy=math.sqrt(sum((b-my)**2 for b in ry))
    if dx<=0 or dy<=0:return None
    return num/(dx*dy)

def _metrics(rows):
    rs=[float(x.get("net_r") if x.get("net_r") is not None else x.get("r_result") or 0.0) for x in rows]
    n=len(rs)
    if not n:
        return {
            "samples":0,"wins":0,"losses":0,"win_rate_pct":0.0,
            "avg_net_r":0.0,"total_net_r":0.0,"profit_factor":0.0,
            "max_drawdown_r":0.0,"recovery_factor":0.0,"lower_bound_r":0.0,
            "spearman_ic":None,
        }
    wins=sum(1 for r in rs if r>0); losses=sum(1 for r in rs if r<0)
    gp=sum(r for r in rs if r>0); gl=abs(sum(r for r in rs if r<0))
    pf=(gp/gl) if gl>0 else (9.99 if gp>0 else 0.0)
    cum=0.0; peak=0.0; maxdd=0.0
    for r in rs:
        cum+=r
        peak=max(peak,cum)
        maxdd=max(maxdd,peak-cum)
    total=sum(rs); avg=total/n
    recovery=(total/maxdd) if maxdd>1e-9 else (9.99 if total>0 else 0.0)
    sd=statistics.stdev(rs) if n>=2 else 0.0
    lower=avg-1.28*(sd/math.sqrt(n)) if n else 0.0
    qualities=[_num(x.get("base_quality"),50.0) for x in rows]
    ic=_spearman(qualities,rs)
    return {
        "samples":n,
        "wins":wins,
        "losses":losses,
        "win_rate_pct":round(100.0*wins/n,2),
        "avg_net_r":round(avg,5),
        "total_net_r":round(total,5),
        "profit_factor":round(min(pf,9.99),4),
        "max_drawdown_r":round(maxdd,4),
        "recovery_factor":round(max(-9.99,min(9.99,recovery)),4),
        "lower_bound_r":round(lower,5),
        "spearman_ic":round(ic,4) if ic is not None else None,
    }

def _normalized_genes(row):
    tags=[]
    for raw in row.get("tags") or []:
        t=str(raw or "").upper().strip()
        if not t or t in _EXCLUDED_TAGS:continue
        if t in _ALLOWED_EXACT or any(t.startswith(p) for p in _ALLOWED_PREFIXES):
            tags.append(t)
    regime=str(row.get("market_regime") or "").upper()
    if regime:
        parts=regime.split("|")
        if parts[0]:tags.append("REGIME:"+parts[0])
        if len(parts)>1 and parts[1]:tags.append("VOLREGIME:"+parts[1])
    c=row.get("_candidate") or {}
    if bool(c.get("execution_eligible")):
        tags.append("EXECUTION_ELIGIBLE")
    if bool(c.get("cost_efficient")):
        tags.append("COST_EFFICIENT")
    return sorted(set(tags))[:12]

def _enriched_rows(outcomes=None,candidates=None):
    outcomes=list(outcomes if outcomes is not None else _read_jsonl(adaptive_trainer.OUTCOMES))
    candidates=list(candidates if candidates is not None else _read_jsonl(adaptive_trainer.CANDIDATES))
    by_id={str(c.get("candidate_id")):c for c in candidates if c.get("candidate_id")}
    cutoff=_now()-timedelta(hours=float(config.ALPHA_FACTORY_LOOKBACK_HOURS))
    rows=[]
    for x in outcomes[-int(config.ALPHA_FACTORY_MAX_EVIDENCE_ROWS)*2:]:
        ts=_parse_ts(x.get("created_at_utc") or x.get("evaluated_at_utc"))
        if not ts or ts<cutoff:continue
        if x.get("geometry_version") and x.get("geometry_version")!=config.TRAINER_GEOMETRY_VERSION:
            continue
        r=_num(x.get("net_r") if x.get("net_r") is not None else x.get("r_result"))
        if r is None:continue
        y=dict(x)
        y["_ts"]=ts
        y["_candidate"]=by_id.get(str(x.get("candidate_id")),{})
        if y.get("base_quality") is None:
            y["base_quality"]=y["_candidate"].get("base_quality")
        y["_genes"]=_normalized_genes(y)
        if len(y["_genes"])>=int(config.ALPHA_FACTORY_GENE_COMBO_MIN):
            rows.append(y)
    rows.sort(key=lambda z:z["_ts"])
    return rows[-int(config.ALPHA_FACTORY_MAX_EVIDENCE_ROWS):]

def _pattern_keys(row):
    genes=row.get("_genes") or []
    strategy=str(row.get("strategy") or "UNKNOWN").upper()
    direction=str(row.get("direction") or "UNKNOWN").upper()
    asset=str(row.get("asset") or "UNKNOWN").upper()
    lo=max(1,int(config.ALPHA_FACTORY_GENE_COMBO_MIN))
    hi=min(len(genes),int(config.ALPHA_FACTORY_GENE_COMBO_MAX))
    for size in range(lo,hi+1):
        for combo in itertools.combinations(genes,size):
            yield ("*",strategy,direction,combo)
            yield (asset,strategy,direction,combo)

def _walk_forward(rows):
    folds=max(2,int(config.ALPHA_FACTORY_WALK_FORWARD_FOLDS))
    n=len(rows)
    chunks=[]
    for i in range(folds):
        a=int(i*n/folds); b=int((i+1)*n/folds)
        if b>a:chunks.append(_metrics(rows[a:b]))
    positive=sum(1 for m in chunks if m["avg_net_r"]>0)
    return {
        "folds":len(chunks),
        "positive_folds":positive,
        "positive_ratio":round(positive/len(chunks),3) if chunks else 0.0,
        "fold_metrics":chunks,
    }

def _decay(rows):
    n=max(4,int(config.ALPHA_FACTORY_DECAY_RECENT_SAMPLES))
    if len(rows)<n*2:
        return {"degraded":False,"recent_samples":min(len(rows),n),"recent_avg_r":None,"prior_avg_r":None,"drop_r":None}
    recent=rows[-n:]; prior=rows[-2*n:-n]
    ra=_metrics(recent)["avg_net_r"]; pa=_metrics(prior)["avg_net_r"]
    drop=pa-ra
    degraded=(
        drop>=float(config.ALPHA_FACTORY_DECAY_DROP_R)
        and pa>0
    ) or (pa>0.03 and ra<-0.03)
    return {
        "degraded":bool(degraded),
        "recent_samples":n,
        "recent_avg_r":ra,
        "prior_avg_r":pa,
        "drop_r":round(drop,5),
    }

def _genome_id(key):
    asset,strategy,direction,genes=key
    raw="|".join([asset,strategy,direction,*genes])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14]

def _evaluate_genome(key,rows):
    rows=sorted(rows,key=lambda x:x["_ts"])
    n=len(rows)
    oos_frac=max(0.15,min(0.50,float(config.ALPHA_FACTORY_OOS_FRACTION)))
    oos_n=max(int(config.ALPHA_FACTORY_MIN_OOS_SAMPLES),int(round(n*oos_frac)))
    if oos_n>=n:oos_n=max(1,n//3)
    train=rows[:-oos_n]; oos=rows[-oos_n:]
    train_m=_metrics(train); oos_m=_metrics(oos); all_m=_metrics(rows)
    wf=_walk_forward(rows); decay=_decay(rows)
    asset,strategy,direction,genes=key

    enough=(
        all_m["samples"]>=int(config.ALPHA_FACTORY_MIN_TOTAL_SAMPLES)
        and train_m["samples"]>=int(config.ALPHA_FACTORY_MIN_TRAIN_SAMPLES)
        and oos_m["samples"]>=int(config.ALPHA_FACTORY_MIN_OOS_SAMPLES)
    )
    status="COLLECTING"
    if enough:
        champion=(
            train_m["avg_net_r"]>0
            and oos_m["avg_net_r"]>=float(config.ALPHA_FACTORY_CHAMPION_MIN_OOS_R)
            and oos_m["profit_factor"]>=float(config.ALPHA_FACTORY_CHAMPION_MIN_PF)
            and oos_m["recovery_factor"]>=float(config.ALPHA_FACTORY_CHAMPION_MIN_RECOVERY)
            and oos_m["max_drawdown_r"]<=float(config.ALPHA_FACTORY_MAX_OOS_DRAWDOWN_R)
            and wf["positive_ratio"]>=0.66
        )
        promising=(
            train_m["avg_net_r"]>=0
            and oos_m["avg_net_r"]>=float(config.ALPHA_FACTORY_PROMISING_MIN_OOS_R)
            and oos_m["profit_factor"]>=float(config.ALPHA_FACTORY_PROMISING_MIN_PF)
            and wf["positive_ratio"]>=0.50
        )
        if decay["degraded"]:
            status="DEGRADED"
        elif champion:
            status="SHADOW_CHAMPION"
        elif promising:
            status="PROMISING"
        elif oos_m["avg_net_r"]<-0.05 and oos_m["profit_factor"]<0.90:
            status="REJECTED"
        else:
            status="CHALLENGER"

    status_bonus={
        "SHADOW_CHAMPION":30,"PROMISING":16,"CHALLENGER":4,
        "COLLECTING":0,"DEGRADED":-12,"REJECTED":-20,
    }.get(status,0)
    score=(
        status_bonus
        + 80.0*oos_m["avg_net_r"]
        + 8.0*min(3.0,oos_m["profit_factor"])
        + 14.0*wf["positive_ratio"]
        + 25.0*oos_m["lower_bound_r"]
        + 5.0*(oos_m["spearman_ic"] or 0.0)
        - 1.4*oos_m["max_drawdown_r"]
        + min(10.0,math.log1p(all_m["samples"])*1.8)
    )
    return {
        "genome_id":_genome_id(key),
        "asset_scope":asset,
        "strategy":strategy,
        "direction":direction,
        "genes":list(genes),
        "status":status,
        "score":round(score,3),
        "train":train_m,
        "oos":oos_m,
        "all":all_m,
        "walk_forward":wf,
        "decay":decay,
        "order_capability":False,
        "model_call_capability":False,
    }

def analyze_rows(outcomes=None,candidates=None):
    rows=_enriched_rows(outcomes,candidates)
    # Global chronological holdout: no pattern discovery, genome ranking or
    # development OOS metric can inspect these last rows. This remains a
    # *rolling research holdout*, not an immutable forward live promotion test.
    frac=max(0.10,min(0.35,float(config.ALPHA_FACTORY_LOCKED_HOLDOUT_FRACTION)))
    n_holdout=max(1,int(round(len(rows)*frac))) if rows else 0
    development=rows[:-n_holdout] if n_holdout else []
    holdout=rows[-n_holdout:] if n_holdout else []
    counts=Counter()
    for row in development:
        counts.update(_pattern_keys(row))

    min_n=int(config.ALPHA_FACTORY_MIN_TOTAL_SAMPLES)
    # Keep extra candidates before expensive metric calculation so a small
    # number of very common but weak patterns cannot crowd out useful genomes.
    keys=[
        k for k,n in counts.most_common(int(config.ALPHA_FACTORY_MAX_GENOMES)*6)
        if n>=min_n
    ]
    wanted=set(keys)
    buckets=defaultdict(list)
    if wanted:
        for row in development:
            for key in _pattern_keys(row):
                if key in wanted:buckets[key].append(row)

    genomes=[_evaluate_genome(k,buckets[k]) for k in keys]
    genomes.sort(key=lambda x:(x["score"],x["oos"]["samples"]),reverse=True)
    genomes=genomes[:int(config.ALPHA_FACTORY_MAX_GENOMES)]
    # Annotate selected genomes only AFTER ranking/truncation. The holdout
    # metrics never influence candidate eligibility, score, or ordering.
    if genomes and holdout:
        selected={(g["asset_scope"],g["strategy"],g["direction"],tuple(g["genes"])):g
                  for g in genomes}
        held_buckets=defaultdict(list)
        for row in holdout:
            for key in _pattern_keys(row):
                if key in selected:held_buckets[key].append(row)
        for key,g in selected.items():
            hm=_metrics(held_buckets[key])
            g["locked_holdout"]=hm
            g["holdout_evidence_status"]=(
                "INSUFFICIENT" if hm["samples"]<int(config.ALPHA_FACTORY_MIN_OOS_SAMPLES)
                else "POSITIVE" if hm["avg_net_r"]>0 else "NON_POSITIVE"
            )
    for g in genomes:
        g.setdefault("locked_holdout",_metrics([]))
        g.setdefault("holdout_evidence_status","INSUFFICIENT")
        g["selection_trials"] = len(keys)
    status_counts=Counter(x["status"] for x in genomes)

    gene_counts=Counter()
    for row in rows:
        gene_counts.update(row.get("_genes") or [])

    return {
        "status":"OK",
        "generated_at_utc":_now().isoformat(),
        "factory_version":"alpha_factory_v1",
        "source":"ADAPTIVE_TRAINER_COST_AWARE_OUTCOMES",
        "lookback_hours":int(config.ALPHA_FACTORY_LOOKBACK_HOURS),
        "evidence_rows":len(rows),
        "development_rows":len(development),
        "locked_holdout_rows":len(holdout),
        "locked_holdout_note":"Rolling chronological audit only; repeated refreshes reuse evidence. No promotion authority.",
        "discovered_patterns":len(counts),
        "selection_trials":len(keys),
        "evaluated_genomes":len(genomes),
        "status_counts":dict(status_counts),
        "gene_catalog":[{"gene":k,"evidence_rows":v} for k,v in gene_counts.most_common(30)],
        "top_genomes":genomes[:50],
        "shadow_champions":[x for x in genomes if x["status"]=="SHADOW_CHAMPION"][:20],
        "promising":[x for x in genomes if x["status"]=="PROMISING"][:20],
        "degraded":[x for x in genomes if x["status"]=="DEGRADED"][:20],
        "order_capability":False,
        "model_call_capability":False,
        "execution_note":"Research only. Promotion does not alter runtime trading or Risk Engine.",
    }

def refresh():
    if not config.ALPHA_FACTORY_ENABLED:
        payload={
            "status":"DISABLED","generated_at_utc":_now().isoformat(),
            "order_capability":False,"model_call_capability":False,
        }
        _atomic_json(SNAPSHOT,payload)
        return payload
    payload=analyze_rows()
    _atomic_json(SNAPSHOT,payload)
    return payload

def summary():
    if not config.ALPHA_FACTORY_ENABLED:
        return {"status":"DISABLED","order_capability":False,"model_call_capability":False}
    try:
        x=json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        generated=_parse_ts(x.get("generated_at_utc"))
        age=(_now()-generated).total_seconds() if generated else None
        x["snapshot_age_seconds"]=round(age,1) if age is not None else None
        x["stale"]=bool(age is not None and age>float(config.ALPHA_FACTORY_SNAPSHOT_MAX_AGE_SECONDS))
        return x
    except Exception:
        return {
            "status":"COLLECTING",
            "generated_at_utc":None,
            "evidence_rows":0,
            "evaluated_genomes":0,
            "top_genomes":[],
            "shadow_champions":[],
            "promising":[],
            "degraded":[],
            "order_capability":False,
            "model_call_capability":False,
        }

if __name__=="__main__":
    print(json.dumps(refresh(),ensure_ascii=False,indent=2))

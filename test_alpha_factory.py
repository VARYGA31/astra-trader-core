#!/usr/bin/env python3
from datetime import datetime, timezone, timedelta
from pathlib import Path
import inspect

import config
import alpha_factory

def _rows(n=60,negative_tail=0):
    now=datetime.now(timezone.utc)
    outcomes=[]; candidates=[]
    for i in range(n):
        cid=f"c{i}"
        r=0.18 if i<n-negative_tail else -0.35
        outcomes.append({
            "candidate_id":cid,
            "created_at_utc":(now-timedelta(minutes=(n-i)*5)).isoformat(),
            "evaluated_at_utc":(now-timedelta(minutes=(n-i)*5-1)).isoformat(),
            "asset":"BTC","strategy":"NORMAL","direction":"LONG",
            "geometry_version":config.TRAINER_GEOMETRY_VERSION,
            "base_quality":70+(i%10),
            "tags":["NORMAL","LONG","4H_TREND_MATCH","1H_TREND_MATCH","15M_MOM_MATCH","VOL_HIGH","SPREAD_TIGHT"],
            "market_regime":"TREND_UP|VOL_NORMAL",
            "net_r":r,"r_result":r,
        })
        candidates.append({
            "candidate_id":cid,
            "base_quality":70+(i%10),
            "execution_eligible":True,
            "cost_efficient":True,
        })
    return outcomes,candidates

def test_alpha_factory_is_shadow_only():
    src=inspect.getsource(alpha_factory)
    assert alpha_factory.ORDER_CAPABILITY is False
    assert alpha_factory.MODEL_CALL_CAPABILITY is False
    for forbidden in ("astra_client","execution_router","trade_cycle.execute","open_fok("):
        assert forbidden not in src,forbidden

def test_positive_oos_can_be_shadow_champion():
    outcomes,candidates=_rows(72,0)
    x=alpha_factory.analyze_rows(outcomes,candidates)
    assert x["status"]=="OK",x
    assert x["evidence_rows"]==72,x
    assert x["evaluated_genomes"]>0,x
    assert x["shadow_champions"],x
    g=x["shadow_champions"][0]
    assert g["oos"]["samples"]>=config.ALPHA_FACTORY_MIN_OOS_SAMPLES,g
    assert g["oos"]["avg_net_r"]>0,g
    assert g["order_capability"] is False,g

def test_decay_marks_recent_breakdown():
    outcomes,candidates=_rows(72,12)
    x=alpha_factory.analyze_rows(outcomes,candidates)
    degraded=[g for g in x["top_genomes"] if g["status"]=="DEGRADED"]
    assert degraded,degraded
    assert degraded[0]["decay"]["degraded"] is True,degraded[0]

if __name__=="__main__":
    test_alpha_factory_is_shadow_only()
    test_positive_oos_can_be_shadow_champion()
    test_decay_marks_recent_breakdown()
    print({"status":"OK","alpha_factory":"SHADOW_ONLY","order_capability":False})

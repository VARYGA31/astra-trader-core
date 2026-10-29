#!/usr/bin/env python3
"""No-network tests: one XAU stop is not grounds to disable the asset."""
from unittest.mock import patch
import observability


def row(asset, side, setup, pnl, id, entry=100, stop=99, notional=100):
    return {
        "event":"OKX_POSITION_CLOSED",
        "close_event_id":str(id),
        "asset":asset,
        "side":side,
        "setup_type":setup,
        "entry":entry,
        "stop_loss":stop,
        "notional_usd":notional,
        "pnl_usd":pnl,
        "timestamp_utc":"2026-10-29T16:17:27+00:00",
    }


def test_one_gold_loss_never_blacklists_market():
    xau=row("XAU","SHORT","TREND_CONTINUATION",-7.972408737,1,4034.9,4049,1444.49)
    with patch.object(observability,"_load_jsonl",return_value=[xau,xau]):
        result=observability.trade_performance()
    assert result["overall"]["trades"]==1,result
    assert result["cohort_policy"]=="OBSERVATION_ONLY_NO_ASSET_BLACKLIST"
    c=result["by_asset_setup_direction"]
    assert len(c)==1 and c[0]["asset"]=="XAU",c
    assert c[0]["trades"]==1 and c[0]["evidence"]=="INSUFFICIENT_SAMPLE",c
    assert c[0]["eligible_for_auto_blacklist"] is False,c


def test_asset_direction_setup_are_independent_and_realized():
    rows=[
        row("BTC","LONG","TREND_CONTINUATION",-2,1),
        row("BTC","SHORT","TREND_CONTINUATION",+3,2),
        row("ETH","SHORT","TREND_CONTINUATION",+5,3),
        row("BTC","SHORT","BREAKOUT",+5,4),
    ]
    with patch.object(observability,"_load_jsonl",return_value=rows):
        res=observability.trade_performance()
    c=res["by_asset_setup_direction"]
    assert len(c)==4,c
    assert res["overall"]["trades"]==4,res
    assert all(z["trades"]==1 and z["eligible_for_auto_blacklist"] is False for z in c),c
    assert {z["side"] for z in c}=={"LONG","SHORT"},c


def test_large_sample_remains_observational():
    rows=[row("AAVE","LONG","COMPRESSION",(-1 if i%2 else 1),i) for i in range(30)]
    with patch.object(observability,"_load_jsonl",return_value=rows):
        c=observability.trade_performance()["by_asset_setup_direction"]
    assert len(c)==1 and c[0]["trades"]==30,c
    assert c[0]["evidence"]=="OBSERVATIONAL_ONLY",c
    assert c[0]["eligible_for_auto_blacklist"] is False,c


if __name__=="__main__":
    test_one_gold_loss_never_blacklists_market()
    test_asset_direction_setup_are_independent_and_realized()
    test_large_sample_remains_observational()
    print("REALIZED_SETUP_LEARNING=PASS; trade_entries_unchanged=true")

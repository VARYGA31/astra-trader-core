#!/usr/bin/env python3
import tempfile
from pathlib import Path
import config, execution_quality, performance_guard, micro_stats

def test_micro_net_edge():
    x=execution_quality.micro_net_edge(
        entry=100,stop=99.8,tp1=100.30,tp2=100.50,
        taker_fee_pct_per_side=0.03,slippage_pct_per_side=0.01,
    )
    assert x["estimated_roundtrip_cost_pct"]==0.08, x
    assert x["net_tp1_r"]>config.MICRO_MIN_NET_TP1_R, x
    assert x["passed"] is True, x

def test_micro_net_edge_rejects_tiny_target():
    x=execution_quality.micro_net_edge(
        entry=100,stop=99.96,tp1=100.04,tp2=100.06,
        taker_fee_pct_per_side=0.05,slippage_pct_per_side=0.02,
    )
    assert x["passed"] is False, x

def test_micro_loss_streak_config():
    old_limit=config.MICRO_LOSS_STREAK_LIMIT
    old_pause=config.MICRO_LOSS_STREAK_PAUSE_SECONDS
    assert old_limit>0 and old_pause>0

def test_micro_stats():
    old=micro_stats.FILE
    try:
        with tempfile.TemporaryDirectory() as td:
            micro_stats.FILE=Path(td)/"micro.jsonl"
            p={"asset":"BTC","decision_context":{"market":{"spot":{"microstructure_source":"OKX_WS_BOOKS5_TRADES"}}}}
            gate={"call_model":True,"reason":"MODEL_GATE_PASS","mtf_quality":88,"mtf":{"passed":True,"direction":"LONG","spread_pct":0.02}}
            d={"action":"LONG","confidence":92}
            x={"status":"REJECTED","reason":"MICRO_NET_EDGE_TOO_LOW","execution_quality":{"micro_net_edge":{"cost_r":0.8,"net_tp1_r":0.2,"net_tp2_r":0.5,"taker_fee_pct_per_side":0.05,"estimated_roundtrip_cost_pct":0.14}}}
            micro_stats.record(p,gate,d,x,True)
            s=micro_stats.summary(6)
            assert s["checks"]==1 and s["net_edge_rejections"]==1,s
    finally:
        micro_stats.FILE=old

if __name__=="__main__":
    test_micro_net_edge();test_micro_net_edge_rejects_tiny_target();test_micro_loss_streak_config();test_micro_stats()
    print({"status":"OK","micro_v2":"NET_EDGE_STATS_LOSS_STREAK"})

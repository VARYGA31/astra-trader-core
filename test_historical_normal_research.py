#!/usr/bin/env python3
"""Pure no-network safety tests for historical_normal_research."""
from datetime import datetime, timezone
import historical_normal_research as h


def test_next_bar_entry_and_conservative_intrabar_exit():
    b=[
        {"open":100,"high":101,"low":99,"close":100},
        {"open":103,"high":110,"low":100,"close":107},
        {"open":107,"high":109,"low":106,"close":108},
    ]
    result=h.trade(b,0,"LONG",2,friction_pct=0.14)
    # Stop first, even when target also touched within the bar.
    assert result["exit"]=="STOP",result
    assert result["end_index"]==1,result
    assert round(result["net_r"],3)==-1.07,result
    # Short and timeout must not be forced into a long side.
    x=h.trade(b,0,"SHORT",1,friction_pct=0.14)
    assert x["exit"]=="STOP",x


def test_only_closed_candles_visible():
    # Need 200 completed 4H bars, and must NEVER include the 200th partial.
    rows=[{"open_time_ms":i*h.BAR["4h"],"close_time_ms":i*h.BAR["4h"],
        "open":100.,"high":101.,"low":99.,"close":100.,"volume":10.}
        for i in range(201)]
    starts=[r["open_time_ms"] for r in rows]
    at_199_open=199*h.BAR["4h"]
    assert h.frame_at(rows,starts,at_199_open+h.BAR["4h"]-1,"4h") is None
    aligned=h.frame_at(rows,starts,at_199_open+h.BAR["4h"],"4h")
    assert aligned and aligned["status"]=="OK",aligned


def test_mixed_requires_1h_and_15m_but_baseline_stays_unmodified():
    def frame(trend,structure,momentum,close=101,volume=1.2):
        return {"status":"OK","close":float(close),
            "indicators":{"ema20":100.,"ema50":99.,"rsi14":60,"atr_pct":1.0},
            "regimes":{"trend":trend,"structure":structure,"momentum":momentum},
            "structure":{"breakout_up":True,"breakout_down":False},
            "changes_pct":{"1bar":0.25},"volume":{"ratio_to_avg20":volume},
            "last_confirmed_close_time_ms":123456}
    frames={"4h":frame("MIXED","BULLISH","BULLISH"),
            "1h":frame("BULLISH","BULLISH","BULLISH"),
            "15m":frame("BULLISH","BULLISH","BULLISH")}
    # The current normal regime can pass mixed 4H if structure + EMA50 align:
    # alternative should never claim a different outcome for such a case.
    original=h.mtf_gate.evaluate({"asset":"BTC","decision_context":{"market":
        {"multi_timeframe":{"status":"OK","frames":frames}}}})
    got=h.signals(frames,"BTC")
    if original["passed"]:
        assert got["normal"]==got["mixed_66"]==got["mixed_72"],got

    frames["15m"]["volume"]["ratio_to_avg20"]=0.3
    got2=h.signals(frames,"BTC")
    assert all(x is None for x in got2.values()),got2


def test_metrics_empty_not_fake_profit():
    m=h.metrics([])
    assert m["trades"]==0 and m["avg_net_r"] is None,m


if __name__=="__main__":
    test_next_bar_entry_and_conservative_intrabar_exit()
    test_only_closed_candles_visible()
    test_mixed_requires_1h_and_15m_but_baseline_stays_unmodified()
    test_metrics_empty_not_fake_profit()
    print("HISTORICAL_NORMAL_OFFLINE_TEST=OK; orders_possible=false")

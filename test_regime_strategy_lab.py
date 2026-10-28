#!/usr/bin/env python3
"""No-network, no-account regression of regime research causality."""
from datetime import datetime, timezone
import regime_strategy_lab as lab


def frame(trend="MIXED",structure="RANGE",momentum="NEUTRAL",
          rsi=50,ema=100,price=100,atr=1,vol=1):
    return {"status":"OK","close":price,
       "regimes":{"trend":trend,"structure":structure,"momentum":momentum},
       "indicators":{"rsi14":rsi,"ema20":ema,"atr_pct":atr},
       "volume":{"ratio_to_avg20":vol}}


def candles(last=100):
    rows=[]
    for i in range(40):
        rows.append({"open_time_ms":i*900000,"close_time_ms":i*900000,
          "open":100.0,"high":101.0,"low":99.0,
          "close":100.0,"volume":1.0})
    rows[-1]["close"]=last
    return rows


def test_reversion_requires_real_range_and_extreme():
    frames={"4h":frame(),"1h":frame(),"15m":frame(rsi=22,ema=101,price=99,vol=0.8)}
    got=lab.signal(frames,candles(last=99),39)
    assert got["range_reversion"][0]=="LONG",got
    frames["1h"]["regimes"]["structure"]="BULLISH"
    assert "range_reversion" not in lab.signal(frames,candles(last=99),39)
    frames["1h"]["regimes"]["structure"]="RANGE"
    frames["15m"]["volume"]["ratio_to_avg20"]=0.2
    assert "range_reversion" not in lab.signal(frames,candles(last=99),39)


def test_compression_uses_only_prior_confirmed_bars():
    frames={
       "4h":frame(trend="MIXED",momentum="NEUTRAL"),
       "1h":frame(trend="MIXED",structure="BULLISH",atr=4.0),
       "15m":frame(price=104,vol=1.5,atr=1.0),
    }
    bars=candles(last=104)
    bars[39]["high"]=104.5
    got=lab.signal(frames,bars,39)
    assert got["compression_breakout"][0]=="LONG",got
    # If lookahead erroneously included the signal bar in prior highs,
    # a valid breakout of prior completed bars would disappear.
    bars[39]["high"]=999
    got2=lab.signal(frames,bars,39)
    assert got2["compression_breakout"]==got["compression_breakout"],(got,got2)


def test_stops_ambiguous_bar_first_and_stress_cost():
    bars=[
      {"open":100,"high":101,"low":99,"close":100},
      {"open":100,"high":110,"low":90,"close":100},
      {"open":101,"high":102,"low":100,"close":101},
    ]
    x=lab.trade(bars,0,"LONG",2,1.5,0.14)
    assert x["exit_reason"]=="STOP" and round(x["net_r"],2)==-1.07,x
    summary=lab.metrics([{"net_r":x["net_r"],"stop_pct":2}],base_cost=0.14)
    assert summary["stress_avg_net_r"]<summary["avg_net_r"],summary


def test_no_fabricated_profit_without_trades():
    z=lab.metrics([])
    assert z["trades"]==0 and z["avg_net_r"] is None and z["stress_avg_net_r"] is None,z


if __name__=="__main__":
    test_reversion_requires_real_range_and_extreme()
    test_compression_uses_only_prior_confirmed_bars()
    test_stops_ambiguous_bar_first_and_stress_cost()
    test_no_fabricated_profit_without_trades()
    print("REGIME_LAB_PURE_TEST=OK; orders_possible=false")

#!/usr/bin/env python3
"""Production NORMAL quality floor must never be lower than order risk floor."""
from unittest.mock import patch
import config
import mtf_gate
import risk_engine


def tf(trend="BULLISH",structure="BULLISH",momentum="NEUTRAL",
       change=0.0,volume=1.0):
    return {"status":"OK","close":101.0,
            "regimes":{"trend":trend,"structure":structure,"momentum":momentum},
            "indicators":{"ema20":100.0,"ema50":99.0,"rsi14":50.0},
            "structure":{"breakout_up":structure=="BULLISH","breakout_down":False},
            "changes_pct":{"1bar":change},
            "volume":{"ratio_to_avg20":volume},
            "last_confirmed_close_time_ms":12345}


def evaluate(asset, high=False):
    f4=tf(momentum="BULLISH" if high else "NEUTRAL")
    f1=tf()
    f15=tf(momentum="BULLISH" if high else "NEUTRAL",change=0.5 if high else -0.1)
    return mtf_gate.evaluate({"asset":asset,"decision_context":{"market":{
       "multi_timeframe":{"status":"OK","frames":{"4h":f4,"1h":f1,"15m":f15}}}}})


def risk_quality_rejection(asset,quality):
    return risk_engine.evaluate({"asset":asset,"action":"LONG",
        "confidence":95,"mtf_quality":quality,"mtf_mode":"NORMAL",
        "strategy_mode":"NORMAL","data_quality":"OK",
        "critical_news_verified":True,"entry":100.0,
        "stop_loss":98.0,"take_profit_1":103.0,"take_profit_2":105.0})


def test_preflight_never_spends_model_on_failing_quality():
    with patch.object(config,"MTF_TRANSITION_ENABLED",False), \
         patch.object(config,"MTF_MIN_QUALITY",72), \
         patch.object(config,"MIN_TRADE_CONFIDENCE",80), \
         patch.object(config,"DEFI_TRADE_MIN_QUALITY",82), \
         patch.object(config,"XAU_MTF_MIN_QUALITY",78):
        for asset, floor in (("BTC",80),("ETH",80),("AAVE",82),("XAU",78)):
            low=evaluate(asset,high=False)
            assert low["quality"]==74.0,low
            assert low["passed"] is False, (asset,low)
            assert low["minimum_quality"]==floor, (asset,low)
            assert "MTF_QUALITY_BELOW_MIN" in low["blockers"], (asset,low)
            assert risk_quality_rejection(asset,74)["reason"]=="MTF_QUALITY_TOO_LOW"
            high=evaluate(asset,high=True)
            assert high["passed"] is True,(asset,high)
            assert high["minimum_quality"]==floor,(asset,high)


def test_floor_never_weakens_existing_configured_mtf_requirement():
    with patch.object(config,"MTF_TRANSITION_ENABLED",False), \
         patch.object(config,"MTF_MIN_QUALITY",85), \
         patch.object(config,"MIN_TRADE_CONFIDENCE",80), \
         patch.object(config,"DEFI_TRADE_MIN_QUALITY",82):
        for asset in ("BTC","AAVE"):
            result=evaluate(asset,high=True)
            assert result["minimum_quality"]==85,(asset,result)


if __name__=="__main__":
    test_preflight_never_spends_model_on_failing_quality()
    test_floor_never_weakens_existing_configured_mtf_requirement()
    print("MTF_RISK_PRECHECK_ALIGNMENT=OK; no_orders=true")

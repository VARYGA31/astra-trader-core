#!/usr/bin/env python3
import tempfile
from pathlib import Path

import config
import micro_decision_gate
import micro_second_shadow

def _tf(ts, change=0.08):
    return {
        "status":"OK",
        "last_confirmed_close_time_ms":ts,
        "close":101.0,
        "changes_pct":{"1bar":change,"3bar":change*2,"6bar":change*3},
        "indicators":{"ema20":100.0,"ema50":99.0,"ema200":95.0,"rsi14":62.0,"atr_pct":0.08},
        "regimes":{"trend":"BULLISH","structure":"BULLISH","momentum":"BULLISH"},
        "structure":{"breakout_up":True,"breakout_down":False,"distance_to_prior_high_pct":0.4,"distance_to_prior_low_pct":1.2},
        "volume":{"ratio_to_avg20":1.5},
    }

def _package(asset="GRAM"):
    return {
        "asset":asset,
        "guards":{
            "market_stale":False,"market_ok":True,"news_ok":True,
            "critical_news_verified":True,"trading_halted":False,
            "cooldown":{"active":False},"loss_streak_pause":{"active":False},
        },
        "account_state":{
            "equity":10000.0,
            "open_positions":1,
            "current_exposure_usd":5000.0,
            "open_assets":["BTC"],
            "exchange_positions":[{"asset":"BTC","side":"LONG"}],
        },
        "decision_context":{
            "news":{"events":[]},
            "market":{
                "multi_timeframe":{"frames":{"1m":_tf(10),"3m":_tf(20),"5m":_tf(30)}},
                "perp_okx":{"bid_price":100.99,"ask_price":101.01},
                "spot":{"order_book":{"imbalance":0.12},"trade_flow":{"buy_sell_ratio":1.2}},
            },
        },
    }

def test_second_signal_is_shadow_only():
    old=micro_decision_gate.STATE_FILE
    try:
        with tempfile.TemporaryDirectory() as td:
            micro_decision_gate.STATE_FILE=Path(td)/"gate.json"
            g=micro_decision_gate.evaluate(_package(),False)
            assert g["call_model"] is True,g
            assert g["second_position_shadow"] is True,g
    finally:
        micro_decision_gate.STATE_FILE=old

def test_shadow_candidate_recording_and_sizing():
    old=micro_second_shadow.FILE
    try:
        with tempfile.TemporaryDirectory() as td:
            micro_second_shadow.FILE=Path(td)/"shadow.json"
            package=_package()
            gate={"mtf_quality":88,"mtf":{"trigger_candle_id":123}}
            decision={
                "asset":"GRAM","action":"LONG","confidence":94,
                "entry":100.0,"stop_loss":99.8,
                "take_profit_1":100.2,"take_profit_2":100.35,
            }
            r=micro_second_shadow.consider(package,decision,gate)
            assert r["status"]=="SHADOW_SECOND_RECORDED",r
            assert r["order_capability"] is False,r
            assert r["shadow_notional_usd"]<=package["account_state"]["equity"]*config.MICRO_SECOND_SHADOW_MAX_POSITION_PCT+1e-9
            assert r["shadow_risk_usd"]<=package["account_state"]["equity"]*config.MICRO_SECOND_SHADOW_RISK_PCT+1e-9
            s=micro_second_shadow.summary()
            assert s["pending"]==1 and s["order_capability"] is False,s
    finally:
        micro_second_shadow.FILE=old

def test_shadow_simulation_net_win_and_loss():
    base={
        "action":"LONG","entry":100.0,"stop_loss":99.8,
        "take_profit_1":100.2,"take_profit_2":100.35,
        "shadow_notional_usd":1000.0,"shadow_risk_usd":2.0,
        "estimated_roundtrip_cost_pct":0.14,
        "created_at_ms":1000,"due_at_ms":400000,
    }
    win=micro_second_shadow.simulate(base,[
        {"ts":61000,"high":100.21,"low":100.05,"close":100.18,"confirmed":True},
        {"ts":121000,"high":100.40,"low":100.10,"close":100.36,"confirmed":True},
    ])
    assert win["status"]=="EVALUATED" and win["net_pnl_usd"]>0,win
    assert win["exit_reason"]=="TP1_TP2",win

    loss=micro_second_shadow.simulate(base,[
        {"ts":61000,"high":100.05,"low":99.70,"close":99.85,"confirmed":True},
    ])
    assert loss["status"]=="EVALUATED" and loss["net_pnl_usd"]<0,loss
    assert loss["exit_reason"]=="STOP_LOSS",loss

def test_same_direction_btc_eth_shadow_is_blocked():
    old=micro_second_shadow.FILE
    try:
        with tempfile.TemporaryDirectory() as td:
            micro_second_shadow.FILE=Path(td)/"shadow.json"
            package=_package("ETH")
            decision={
                "asset":"ETH","action":"LONG","confidence":95,
                "entry":100.0,"stop_loss":99.8,
                "take_profit_1":100.2,"take_profit_2":100.35,
            }
            r=micro_second_shadow.consider(package,decision,{"mtf_quality":90,"mtf":{"trigger_candle_id":555}})
            assert r["status"]=="SKIPPED" and r["reason"]=="BTC_ETH_SAME_DIRECTION",r
    finally:
        micro_second_shadow.FILE=old

if __name__=="__main__":
    test_second_signal_is_shadow_only()
    test_shadow_candidate_recording_and_sizing()
    test_shadow_simulation_net_win_and_loss()
    test_same_direction_btc_eth_shadow_is_blocked()
    print({
        "status":"OK",
        "second_position":"SHADOW_ONLY",
        "order_capability":False,
    })

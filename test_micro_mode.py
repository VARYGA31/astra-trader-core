#!/usr/bin/env python3
import config
import micro_gate
import risk_engine
import execution_quality
import okx_position_monitor

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

def test_micro_gate_long():
    package={
        "asset":"BTC",
        "decision_context":{"market":{
            "multi_timeframe":{"frames":{"1m":_tf(1),"3m":_tf(2),"5m":_tf(3)}},
            "perp_okx":{"bid_price":100.99,"ask_price":101.01},
            "spot":{"order_book":{"imbalance":0.12},"trade_flow":{"buy_sell_ratio":1.2}},
        }}
    }
    g=micro_gate.evaluate(package)
    assert g["passed"] is True
    assert g["direction"]=="LONG"
    assert g["quality"]>=config.MICRO_MIN_QUALITY

def test_micro_risk_is_bounded():
    d={
        "asset":"BTC","action":"LONG","data_quality":"OK","critical_news_verified":True,
        "confidence":94,"mtf_quality":92,"mtf_mode":"MICRO","strategy_mode":"MICRO",
        "entry":100.0,"stop_loss":99.8,"take_profit_1":100.2,"take_profit_2":100.35,
        "volatility_regime":"NORMAL","equity":10000.0,"initial_equity":10000.0,
        "daily_pnl":0.0,"open_positions":0,"current_exposure_usd":0.0,
    }
    r=risk_engine.evaluate(d)
    assert r["status"]=="APPROVED", r
    assert r["leverage"]<=config.MICRO_MAX_LEVERAGE
    assert r["position_notional_usd"]<=10000.0*config.MICRO_MAX_POSITION_PCT+1e-9
    assert r["actual_risk_pct"]<=config.MICRO_HARD_RISK_PCT+1e-12

def test_micro_execution_rr_and_slippage():
    r1,r2=execution_quality.min_rr_for_mode("MICRO")
    assert r1==config.MICRO_MIN_TP1_R
    assert r2==config.MICRO_MIN_TP2_R
    assert execution_quality.max_slippage_pct("BTC","MICRO")==config.MICRO_MAX_ENTRY_SLIPPAGE_PCT

def test_micro_time_stop_helper():
    rec={"strategy_mode":"MICRO","opened_at_utc":"2026-01-01T00:00:00+00:00"}
    assert okx_position_monitor._micro_time_stop_due(rec, now_ts=1767225901.0) is True
    rec["strategy_mode"]="SCALP"
    assert okx_position_monitor._micro_time_stop_due(rec, now_ts=1767225901.0) is False

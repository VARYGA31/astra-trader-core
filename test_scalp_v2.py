#!/usr/bin/env python3
"""Pure SCALP v2 PRIME/FAST + risk test. No network, OpenAI or orders."""
import json
import config,scalp_gate,risk_engine,execution_quality

def tf(trend,structure,momentum,close=100,ema20=99,rsi=60,atr_pct=.25,change=.2,vol=1.2,breakout=False,candle=1):
    return {"status":"OK","close":close,"last_confirmed_close_time_ms":candle,
        "indicators":{"ema20":ema20,"ema50":98,"ema200":95,"rsi14":rsi,"atr_pct":atr_pct},
        "regimes":{"trend":trend,"structure":structure,"momentum":momentum},
        "changes_pct":{"1bar":change,"6bar":.5},
        "structure":{"breakout_up":breakout,"breakout_down":False,"distance_to_prior_high_pct":.5,"distance_to_prior_low_pct":1.0},
        "volume":{"ratio_to_avg20":vol}}

def package(tf5,spread=.02):
    bid=100*(1-spread/200); ask=100*(1+spread/200)
    return {"asset":"BTC","strategy_mode":"SCALP","decision_context":{"market":{
        "multi_timeframe":{"status":"OK","frames":{
            "1h":tf("BULLISH","BULLISH","BULLISH",candle=10),
            "15m":tf("BULLISH","BULLISH","BULLISH",candle=20),
            "5m":tf5,
        }},"perp_okx":{"bid_price":bid,"ask_price":ask},
        "spot":{"order_book":{"imbalance":.05},"trade_flow":{"buy_sell_ratio":1.1}},
    }}}

prime5=tf("BULLISH","BULLISH","BULLISH",change=.15,vol=1.2,breakout=True,candle=30)
g1=scalp_gate.evaluate(package(prime5))
assert g1["passed"] and g1["tier"]=="PRIME",g1

# FAST: make only 3/5 trigger components true: above EMA20, positive bar, volume.
fast5=tf("MIXED","RANGE","NEUTRAL",close=100,ema20=99,change=.12,vol=1.15,breakout=False,candle=31)
g2=scalp_gate.evaluate(package(fast5,spread=.03))
assert g2["passed"] and g2["tier"]=="FAST",g2

r_fast=risk_engine.evaluate({
    "asset":"BTC","action":"LONG","strategy_mode":"SCALP","mtf_mode":"SCALP","scalp_tier":"FAST",
    "data_quality":"OK","critical_news_verified":True,
    "entry":100,"stop_loss":99.5,"take_profit_1":100.5,"take_profit_2":100.76,
    "confidence":90,"mtf_quality":80,"equity":5000,"initial_equity":5000,"daily_pnl":0,
    "open_positions":0,"current_exposure_usd":0,"asset_already_open":False,"volatility_regime":"NORMAL",
})
assert r_fast["status"]=="APPROVED",r_fast
assert r_fast["leverage"]<=3.0,r_fast
assert r_fast["risk_pct_budget"]<=.0035+1e-12,r_fast
assert execution_quality.min_rr_for_mode("SCALP","FAST")== (config.SCALP_FAST_MIN_TP1_R,config.SCALP_FAST_MIN_TP2_R)

print(json.dumps({
    "status":"OK","will_open_order":False,"will_close_order":False,"will_call_model":False,
    "prime":{"passed":g1["passed"],"tier":g1["tier"],"quality":g1["quality"]},
    "fast":{"passed":g2["passed"],"tier":g2["tier"],"quality":g2["quality"],"trigger_count":g2["candidates"][0]["trigger_5m"]["count"]},
    "fast_risk_pct":r_fast["risk_pct_budget"],"fast_leverage":r_fast["leverage"],
    "fast_tp1_min_r":config.SCALP_FAST_MIN_TP1_R,"fast_tp2_min_r":config.SCALP_FAST_MIN_TP2_R,
},ensure_ascii=False,indent=2))

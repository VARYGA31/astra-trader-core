#!/usr/bin/env python3
"""Pure SCALP logic test: no network, no OpenAI, no orders."""
import json
import config,scalp_gate,risk_engine,execution_quality

def tf(trend,structure,momentum,close=100,ema20=99,rsi=60,atr_pct=.25,change=.2,vol=1.2,breakout=False,candle=1):
    return {"status":"OK","close":close,"last_confirmed_close_time_ms":candle,
        "indicators":{"ema20":ema20,"ema50":98,"ema200":95,"rsi14":rsi,"atr_pct":atr_pct},
        "regimes":{"trend":trend,"structure":structure,"momentum":momentum},
        "changes_pct":{"1bar":change,"6bar":.5},
        "structure":{"breakout_up":breakout,"breakout_down":False,"distance_to_prior_high_pct":.5,"distance_to_prior_low_pct":1.0},
        "volume":{"ratio_to_avg20":vol}}

package={"asset":"BTC","strategy_mode":"SCALP","decision_context":{"market":{
    "multi_timeframe":{"status":"OK","frames":{
        "1h":tf("BULLISH","BULLISH","BULLISH",candle=10),
        "15m":tf("BULLISH","BULLISH","BULLISH",candle=20),
        "5m":tf("BULLISH","BULLISH","BULLISH",change=.15,breakout=True,candle=30),
        "4h":tf("MIXED","RANGE","NEUTRAL",candle=40),
    }},
    "perp_okx":{"bid_price":99.99,"ask_price":100.01},
    "spot":{"order_book":{"imbalance":.05},"trade_flow":{"buy_sell_ratio":1.1}},
}}}
g=scalp_gate.evaluate(package)
assert g["passed"] and g["direction"]=="LONG" and g["mode"]=="SCALP",g
assert g["trigger_candle_id"]==30,g

r=risk_engine.evaluate({
    "asset":"BTC","action":"LONG","strategy_mode":"SCALP","mtf_mode":"SCALP",
    "data_quality":"OK","critical_news_verified":True,
    "entry":100,"stop_loss":99.5,"take_profit_1":100.5,"take_profit_2":100.81,
    "confidence":93,"mtf_quality":92,"equity":5000,"initial_equity":5000,
    "daily_pnl":0,"open_positions":0,"current_exposure_usd":0,"asset_already_open":False,
    "volatility_regime":"NORMAL",
})
assert r["status"]=="APPROVED",r
assert r["strategy_mode"]=="SCALP",r
assert r["leverage"]==7.0,r
assert abs(r["risk_pct_budget"]-.0075)<1e-12,r
assert execution_quality.min_rr_for_mode("SCALP")== (config.SCALP_MIN_TP1_R,config.SCALP_MIN_TP2_R)
print(json.dumps({
    "status":"OK","will_open_order":False,"will_close_order":False,"will_call_model":False,
    "scalp_gate_passed":g["passed"],"direction":g["direction"],"quality":g["quality"],
    "timeframes":"1H -> 15M -> 5M","risk_pct":r["risk_pct_budget"],"leverage":r["leverage"],
    "tp1_min_r":config.SCALP_MIN_TP1_R,"tp2_min_r":config.SCALP_MIN_TP2_R,
},ensure_ascii=False,indent=2))

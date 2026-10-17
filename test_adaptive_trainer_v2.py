#!/usr/bin/env python3
"""Pure Trainer v2 regression. No network, OpenAI or orders."""
import json
import config
import adaptive_trainer
import risk_engine

def frame(trend="BULLISH",structure="BULLISH",momentum="BULLISH",close=100.0,atr_pct=0.25,vol=1.6,breakout=True):
    return {
        "status":"OK",
        "last_confirmed_close_time_ms":1234567890,
        "close":close,
        "changes_pct":{"1bar":0.25,"3bar":0.55,"6bar":0.8},
        "indicators":{"ema20":99.5,"ema50":99.0,"ema200":98.0,"rsi14":60.0,"atr14":0.25,"atr_pct":atr_pct},
        "regimes":{"trend":trend,"structure":structure,"momentum":momentum},
        "structure":{"breakout_up":breakout,"breakout_down":False,"prior_20_high":99.8,"prior_20_low":98.5},
        "volume":{"ratio_to_avg20":vol},
        "last_candle":{"open":99.7,"high":100.1,"low":99.6,"close":100.0},
    }

def package():
    frames={
        "5m":frame(atr_pct=0.22),
        "15m":frame(atr_pct=0.45),
        "1h":frame(atr_pct=0.75),
        "4h":frame(atr_pct=1.2),
    }
    return {
        "asset":"BTC",
        "guards":{
            "market_stale":False,"market_ok":True,"news_ok":True,
            "critical_news_verified":True,
        },
        "decision_context":{"market":{
            "multi_timeframe":{"frames":frames},
            "perp_okx":{"last_price":100.0,"bid_price":99.99,"ask_price":100.01},
            "spot":{
                "price":100.0,
                "order_book":{"imbalance":0.22},
                "trade_flow":{"buy_sell_ratio":1.45},
            },
            "data_quality":{"status":"OK"},
        }},
    }

p=package()
rows=adaptive_trainer.build_candidates({"BTC":p})
assert len(rows)==2,rows
scalp=next(x for x in rows if x["strategy"]=="SCALP")
normal=next(x for x in rows if x["strategy"]=="NORMAL")
assert scalp["direction"]=="LONG",scalp
assert normal["direction"]=="LONG",normal
assert scalp["base_quality"]>=config.ADAPTIVE_TRAINER_MIN_MODEL_QUALITY,scalp
assert scalp["execution_eligible"] is True,scalp
assert scalp["stop_loss"]<scalp["entry"]<scalp["take_profit_1"]<scalp["take_profit_2"],scalp

d={
    "asset":"BTC","action":"LONG",
    "entry":scalp["entry"],"stop_loss":scalp["stop_loss"],
    "take_profit_1":scalp["take_profit_1"],"take_profit_2":scalp["take_profit_2"],
    "confidence":92.0,"mtf_quality":scalp["base_quality"],"mtf_mode":"SCALP",
    "strategy_mode":"SCALP","scalp_tier":scalp["scalp_tier"],
    "data_quality":"OK","critical_news_verified":True,
    "equity":5000.0,"initial_equity":5000.0,"daily_pnl":0.0,
    "open_positions":0,"current_exposure_usd":0.0,"asset_already_open":False,
    "volatility_regime":"NORMAL",
}
r=risk_engine.evaluate(d)
assert r["status"]=="APPROVED",r

positive=[{
    "asset":"BTC","strategy":"SCALP","direction":"LONG",
    "tags":scalp["tags"],"market_regime":scalp.get("market_regime"),"geometry_version":scalp.get("geometry_version"),"r_result":1.5
} for _ in range(30)]
negative=[{
    "asset":"BTC","strategy":"SCALP","direction":"LONG",
    "tags":scalp["tags"],"market_regime":scalp.get("market_regime"),"geometry_version":scalp.get("geometry_version"),"r_result":-1.0
} for _ in range(30)]
pos=adaptive_trainer._similar_stats(scalp,positive)
neg=adaptive_trainer._similar_stats(scalp,negative)
assert pos["adjustment"]>0,pos
assert neg["adjustment"]<0,neg

print(json.dumps({
    "status":"OK",
    "will_open_order":False,
    "will_close_order":False,
    "will_call_model":False,
    "candidate_generation":"OK",
    "risk_alignment":"OK",
    "positive_learning_adjustment":pos["adjustment"],
    "negative_learning_adjustment":neg["adjustment"],
    "scalp_quality":scalp["base_quality"],
    "scalp_tier":scalp["scalp_tier"],
},ensure_ascii=False,indent=2))

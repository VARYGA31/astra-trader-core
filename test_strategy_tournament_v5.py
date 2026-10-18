#!/usr/bin/env python3
"""Pure Strategy Tournament v5 regression. No network, OpenAI or orders."""
import json
from datetime import datetime,timezone,timedelta

import config
import adaptive_trainer
import risk_engine
import strategy_tournament

def frame(trend="BULLISH",structure="BULLISH",momentum="BULLISH",close=100.0,atr_pct=0.35,vol=1.6,breakout=True,rsi=60.0):
    return {
        "status":"OK",
        "last_confirmed_close_time_ms":1700000000000,
        "close":close,
        "changes_pct":{"1bar":0.25,"3bar":0.55,"6bar":0.8},
        "indicators":{"ema20":99.7,"ema50":99.0,"ema200":98.0,"rsi14":rsi,"atr14":0.35,"atr_pct":atr_pct},
        "regimes":{"trend":trend,"structure":structure,"momentum":momentum},
        "structure":{"breakout_up":breakout,"breakout_down":False,"prior_20_high":99.8,"prior_20_low":98.5},
        "volume":{"ratio_to_avg20":vol},
        "last_candle":{"open":99.7,"high":100.1,"low":99.6,"close":100.0},
    }

def package():
    frames={
        "5m":frame(atr_pct=0.30),
        "15m":frame(atr_pct=0.45),
        "1h":frame(atr_pct=0.75),
        "4h":frame(atr_pct=1.20),
    }
    return {
        "asset":"BTC",
        "guards":{
            "market_stale":False,"market_ok":True,"news_ok":True,
            "critical_news_verified":True,"trading_halted":False,
            "cooldown":{"active":False},"loss_streak_pause":{"active":False},
            "asset_already_open":False,
        },
        "account_state":{"open_positions":0},
        "decision_context":{"market":{
            "multi_timeframe":{"frames":frames},
            "perp_okx":{"last_price":100.0,"bid_price":99.99,"ask_price":100.01,"funding_rate":0.0001},
            "spot":{
                "price":100.0,
                "order_book":{"imbalance":0.22},
                "trade_flow":{"buy_sell_ratio":1.45},
            },
            "data_quality":{"status":"OK"},
        }},
    }

rows=strategy_tournament.build_candidates({"BTC":package()})
assert len(rows)==len(config.TOURNAMENT_ARCHETYPES),rows
assert {x["archetype"] for x in rows}==set(config.TOURNAMENT_ARCHETYPES),rows
assert all(x["geometry_version"]==config.TRAINER_GEOMETRY_VERSION for x in rows),rows

trend=next(x for x in rows if x["archetype"]=="TREND_FOLLOW")
assert trend["direction"]=="LONG",trend
assert trend["strategy"]=="NORMAL",trend
assert trend["cost_efficient"] is True,trend

# Synthetic empirical evidence: same market state, healthy positive NET expectancy.
base_time=datetime.now(timezone.utc)-timedelta(hours=10)
positive=[]
for i in range(60):
    positive.append({
        "evaluated_at_utc":(base_time+timedelta(minutes=i)).isoformat(),
        "asset":"BTC","archetype":"TREND_FOLLOW","strategy":"NORMAL",
        "direction":"LONG","market_regime":trend["market_regime"],
        "geometry_version":config.TRAINER_GEOMETRY_VERSION,
        "tags":trend["tags"],
        "net_r":0.8 if i%2==0 else -0.3,
        "r_result":0.8 if i%2==0 else -0.3,
    })
gate=strategy_tournament.champion_gate(trend,positive)
assert gate["champion"] is True,gate
assert gate["stats"]["broad"]["avg_net_r"]>0,gate
assert gate["stats"]["broad"]["profit_factor"]>1,gate
assert gate["risk_multiplier"]<=1.0,gate

negative=[]
for i in range(60):
    negative.append({
        "evaluated_at_utc":(base_time+timedelta(minutes=i)).isoformat(),
        "asset":"BTC","archetype":"TREND_FOLLOW","strategy":"NORMAL",
        "direction":"LONG","market_regime":trend["market_regime"],
        "geometry_version":config.TRAINER_GEOMETRY_VERSION,
        "tags":trend["tags"],
        "net_r":0.2 if i%3==0 else -0.7,
        "r_result":0.2 if i%3==0 else -0.7,
    })
bad=strategy_tournament.champion_gate(trend,negative)
assert bad["champion"] is False,bad

# Risk Engine must reduce, never increase, risk for new tournament champions.
decision={
    "asset":"BTC","action":"LONG",
    "entry":100.0,"stop_loss":99.0,"take_profit_1":101.3,"take_profit_2":102.1,
    "confidence":90.0,"mtf_quality":85.0,"mtf_mode":"NORMAL","strategy_mode":"NORMAL",
    "data_quality":"OK","critical_news_verified":True,
    "equity":5000.0,"initial_equity":5000.0,"daily_pnl":0.0,
    "open_positions":0,"current_exposure_usd":0.0,"asset_already_open":False,
    "volatility_regime":"NORMAL",
}
full=risk_engine.evaluate(dict(decision))
half=risk_engine.evaluate({**decision,"tournament_risk_multiplier":0.5})
assert full["status"]=="APPROVED",full
assert half["status"]=="APPROVED",half
assert half["risk_pct_budget"]<full["risk_pct_budget"],(full,half)
assert abs(half["risk_pct_budget"]-full["risk_pct_budget"]*0.5)<1e-12,(full,half)

print(json.dumps({
    "status":"OK",
    "will_open_order":False,
    "will_close_order":False,
    "will_call_model":False,
    "archetypes":sorted(config.TOURNAMENT_ARCHETYPES),
    "positive_champion":"OK",
    "negative_challenger":"OK",
    "champion_risk_scaling":"OK",
    "positive_avg_net_r":gate["stats"]["broad"]["avg_net_r"],
    "positive_profit_factor":gate["stats"]["broad"]["profit_factor"],
},ensure_ascii=False,indent=2))

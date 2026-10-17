#!/usr/bin/env python3
"""Pure ASTRA Execution v4 regression. No network, OpenAI or orders."""
import json
import math

import config
import adaptive_client
import adaptive_trainer
import risk_engine
import trade_cycle

# 1) Exact effective quality floors must match what Risk Engine can actually size.
req=adaptive_client._execution_requirements()
assert req["NORMAL"]["min_setup_quality"]==max(config.MTF_MIN_QUALITY,config.MIN_TRADE_CONFIDENCE),req
assert req["SCALP_PRIME"]["min_setup_quality"]==max(config.SCALP_MIN_QUALITY,config.SCALP_MIN_TRADE_CONFIDENCE),req
assert req["SCALP_FAST"]["min_setup_quality"]==config.SCALP_FAST_MIN_QUALITY,req

# 2) Cost-aware geometry widens stop distance instead of pretending friction is free.
raw={
    "asset":"BTC","strategy":"SCALP","direction":"LONG",
    "entry":100.0,"stop_loss":99.85,"take_profit_1":100.165,"take_profit_2":100.255,
    "stop_pct":0.15,"tp1_r":1.10,"tp2_r":1.70,
    "spread_pct":0.02,"funding_rate":0.0001,"time_horizon_minutes":60,
    "tags":["SCALP","LONG"],"market_regime":"TREND_UP|VOL_NORMAL",
}
adj=adaptive_trainer._apply_cost_aware_geometry(raw)
assert adj["geometry_version"]==config.TRAINER_GEOMETRY_VERSION,adj
assert adj["cost_efficient"] is True,adj
assert adj["stop_pct"]>=raw["stop_pct"],adj
assert adj["estimated_cost"]["cost_r"]<=config.TRAINER_EXECUTION_MAX_COST_R+1e-9,adj
risk=abs(adj["entry"]-adj["stop_loss"])
assert math.isclose(abs(adj["take_profit_1"]-adj["entry"])/risk,adj["tp1_r"],rel_tol=1e-9),adj
assert math.isclose(abs(adj["take_profit_2"]-adj["entry"])/risk,adj["tp2_r"],rel_tol=1e-9),adj

# 3) Live-entry rebasing must preserve exact R:R for Trainer candidates.
decision={
    "trainer_candidate_id":"abc123","setup_type":"TRAINER_V2",
    "entry":100.0,"stop_loss":99.5,"take_profit_1":100.6,"take_profit_2":101.0,
}
rebased,info=trade_cycle._rebase_trainer_levels(decision,100.1)
assert info["rebased"] is True,info
rr_before_1=abs(decision["take_profit_1"]-decision["entry"])/abs(decision["entry"]-decision["stop_loss"])
rr_after_1=abs(rebased["take_profit_1"]-rebased["entry"])/abs(rebased["entry"]-rebased["stop_loss"])
rr_before_2=abs(decision["take_profit_2"]-decision["entry"])/abs(decision["entry"]-decision["stop_loss"])
rr_after_2=abs(rebased["take_profit_2"]-rebased["entry"])/abs(rebased["entry"]-rebased["stop_loss"])
assert math.isclose(rr_before_1,rr_after_1,rel_tol=1e-12),(decision,rebased)
assert math.isclose(rr_before_2,rr_after_2,rel_tol=1e-12),(decision,rebased)

# 4) NORMAL quality=80 is executable; old 72-79 hidden reject is gone.
normal={
    "asset":"BTC","action":"LONG",
    "entry":100.0,"stop_loss":99.0,"take_profit_1":101.3,"take_profit_2":102.1,
    "confidence":85.0,"mtf_quality":80.0,"mtf_mode":"NORMAL","strategy_mode":"NORMAL",
    "data_quality":"OK","critical_news_verified":True,
    "equity":5000.0,"initial_equity":5000.0,"daily_pnl":0.0,
    "open_positions":0,"current_exposure_usd":0.0,"asset_already_open":False,
    "volatility_regime":"NORMAL",
}
r=risk_engine.evaluate(normal)
assert r["status"]=="APPROVED",r

too_low=dict(normal);too_low["mtf_quality"]=79.0
r2=risk_engine.evaluate(too_low)
assert r2["status"]=="REJECTED" and r2["reason"]=="MTF_QUALITY_TOO_LOW",r2

print(json.dumps({
    "status":"OK",
    "will_open_order":False,
    "will_close_order":False,
    "will_call_model":False,
    "effective_quality_alignment":"OK",
    "cost_aware_geometry":"OK",
    "trainer_live_rebase":"OK",
    "normal_quality_80_approved":True,
    "normal_quality_79_rejected_early":True,
    "adjusted_cost_r":adj["estimated_cost"]["cost_r"],
    "adjusted_stop_pct":adj["stop_pct"],
},ensure_ascii=False,indent=2))

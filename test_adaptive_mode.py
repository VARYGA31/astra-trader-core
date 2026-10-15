#!/usr/bin/env python3
"""Pure ASTRA ADAPTIVE v1 test. No network, OpenAI or orders."""
import json
import tempfile
from pathlib import Path

import strategy_mode
import adaptive_client
import adaptive_engine
import adaptive_memory

packages={
    "BTC":{"asset":"BTC","timeframe":"5m","strategy_mode":"AUTO"},
    "ETH":{"asset":"ETH","timeframe":"5m","strategy_mode":"AUTO"},
    "GRAM":{"asset":"GRAM","timeframe":"5m","strategy_mode":"AUTO"},
}

raw={
    "market_summary":"synthetic test",
    "assets":[
        {"asset":"BTC","score":65,"bias":"LONG","preferred_strategy":"WAIT","actionable":False,"confidence":70,"reason":"mixed"},
        {"asset":"ETH","score":88,"bias":"SHORT","preferred_strategy":"SCALP","actionable":True,"confidence":90,"reason":"strong short"},
        {"asset":"GRAM","score":55,"bias":"NEUTRAL","preferred_strategy":"WAIT","actionable":False,"confidence":60,"reason":"range"},
    ],
    "best_opportunity":{
        "asset":"ETH","action":"SHORT","strategy":"SCALP","scalp_tier":"FAST",
        "setup_quality":82,"confidence":90,"entry":100,"stop_loss":100.5,
        "take_profit_1":99.5,"take_profit_2":99.2,
        "time_horizon_minutes":30,"setup_type":"MOMENTUM_SCALP",
        "volatility_regime":"NORMAL","reason":"synthetic"
    }
}
norm=adaptive_client.normalize(raw,packages)
assert norm["best_opportunity"]["asset"]=="ETH",norm
assert norm["best_opportunity"]["action"]=="SHORT",norm
assert norm["best_opportunity"]["strategy"]=="SCALP",norm
assert norm["best_opportunity"]["scalp_tier"]=="FAST",norm

d=adaptive_engine._decision_from_best(norm["best_opportunity"],{
    "decision_context":{"market":{"data_quality":{"status":"OK"}}}
})
assert d["adaptive_mode"] is True,d
assert d["strategy_mode"]=="SCALP",d
assert d["mtf_quality"]==82.0,d

old=strategy_mode.FILE
try:
    with tempfile.TemporaryDirectory() as td:
        strategy_mode.FILE=Path(td)/"strategy_mode.json"
        strategy_mode.set_mode("AUTO","TEST")
        assert strategy_mode.get_mode()=="AUTO"
        assert strategy_mode.switch_check("NORMAL","AUTO",0)["allowed"] is True
        assert strategy_mode.switch_check("NORMAL","AUTO",1)["allowed"] is False
finally:
    strategy_mode.FILE=old

print(json.dumps({
    "status":"OK",
    "will_open_order":False,
    "will_close_order":False,
    "will_call_model":False,
    "auto_mode":"OK",
    "multi_asset_normalization":"OK",
    "adaptive_decision_conversion":"OK",
    "best_asset":norm["best_opportunity"]["asset"],
    "best_strategy":norm["best_opportunity"]["strategy"],
},ensure_ascii=False,indent=2))

#!/usr/bin/env python3
"""Shadow-only crypto learning loop.

This module keeps Adaptive Trainer and Strategy Tournament learning alive after
AUTO stopped being a tradable runtime mode. It never calls the model and never
routes an order.
"""
import time
from datetime import datetime, timezone

import config
import trade_cycle
import adaptive_trainer
import strategy_tournament

ORDER_CAPABILITY=False
MODEL_CALL_CAPABILITY=False

STATE={
    "status":"STARTING",
    "last_error":None,
    "last_run_at_utc":None,
    "last_result":None,
}

def _now():
    return datetime.now(timezone.utc).isoformat()

def run_once():
    packages={
        a:trade_cycle.prepare(a,config.ADAPTIVE_NEWS_HOURS,"NORMAL")
        for a in config.ADAPTIVE_ALLOWED_ASSETS
    }
    trainer=adaptive_trainer.process(packages)
    tournament=(
        strategy_tournament.process(packages)
        if config.STRATEGY_TOURNAMENT_V5_ENABLED else {"status":"DISABLED"}
    )
    result={
        "status":"OK",
        "trainer":{
            "recorded":trainer.get("recorded"),
            "evaluated":trainer.get("evaluated"),
            "best":trainer.get("best"),
        },
        "tournament":{
            "recorded":tournament.get("recorded"),
            "evaluated":tournament.get("evaluated"),
            "best":tournament.get("best"),
            "champions":len(tournament.get("champions") or []),
        },
        "order_capability":ORDER_CAPABILITY,
        "model_calls":0,
    }
    STATE.update({
        "status":"OK","last_error":None,
        "last_run_at_utc":_now(),"last_result":result,
    })
    return result

def run_forever():
    if not config.CRYPTO_SHADOW_LAB_ENABLED:
        STATE.update({"status":"DISABLED","last_error":None})
        return
    while True:
        try:
            run_once()
        except Exception as e:
            STATE.update({"status":"DEGRADED","last_error":str(e),"last_run_at_utc":_now()})
        time.sleep(max(60,int(config.CRYPTO_SHADOW_LAB_INTERVAL_SECONDS)))

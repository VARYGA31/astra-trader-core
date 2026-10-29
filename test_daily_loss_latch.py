#!/usr/bin/env python3
"""No-network regression: UTC daily loss must be sticky, even after equity bounces."""
import tempfile
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch

import config
import daily_loss_latch
import risk_engine


def at(day, hour=12):
    return datetime(2026,10,day,hour,tzinfo=timezone.utc)


def test_persisted_daily_breach_and_utc_reset():
    with tempfile.TemporaryDirectory() as root, \
         patch.object(daily_loss_latch,"FILE",Path(root)/"latch.json"), \
         patch.object(config,"DAILY_LOSS_LIMIT_PCT",0.06):
        before=daily_loss_latch.observe(100,-5.99,asof=at(29,8))
        assert before["latched"] is False,before
        first=daily_loss_latch.observe(100,-6.01,asof=at(29,9))
        assert first["latched"] is True,first
        # A returning deposit, recovery or oscillating mark PnL cannot clear.
        recovered=daily_loss_latch.observe(100,+10.0,asof=at(29,14))
        assert recovered["latched"] is True,recovered
        assert recovered["first_breach_at_utc"]==first["first_breach_at_utc"]
        again=daily_loss_latch.observe(100,0,asof=at(29,23))
        assert again["latched"] is True,again
        next_day=daily_loss_latch.observe(100,0,asof=at(30,0))
        assert next_day["latched"] is False,next_day
        next_day_breach=daily_loss_latch.observe(100,-10,asof=at(30,1))
        assert next_day_breach["latched"] is True,next_day_breach


def test_storage_or_input_corruption_is_fail_closed():
    with tempfile.TemporaryDirectory() as root, \
         patch.object(daily_loss_latch,"FILE",Path(root)/"latch.json"):
        assert daily_loss_latch.observe(0,0,asof=at(29))["latched"] is True
        assert daily_loss_latch.observe(100,float("nan"),asof=at(29))["latched"] is True
        daily_loss_latch.FILE.write_text("{bad",encoding="utf-8")
        err=daily_loss_latch.observe(100,0,asof=at(29))
        assert err["latched"] is True and err["reason"]=="LATCH_STATE_UNREADABLE",err


def test_risk_engine_defense_in_depth():
    raw={
        "asset":"BTC","action":"LONG","data_quality":"OK",
        "critical_news_verified":True,"equity":10000,
        "initial_equity":10000,"daily_pnl":0,
        "confidence":95,"mtf_quality":95,
        "mtf_mode":"NORMAL","strategy_mode":"NORMAL",
        "entry":100,"stop_loss":98,"take_profit_1":103,"take_profit_2":105,
        "daily_loss_latched":True,
    }
    result=risk_engine.evaluate(raw)
    assert result["status"]=="REJECTED",result
    assert result["reason"]=="DAILY_LOSS_LIMIT_REACHED" and result["latched"] is True,result


if __name__=="__main__":
    test_persisted_daily_breach_and_utc_reset()
    test_storage_or_input_corruption_is_fail_closed()
    test_risk_engine_defense_in_depth()
    print("STICKY_DAILY_LOSS_GUARD=PASS; order_authority=false")

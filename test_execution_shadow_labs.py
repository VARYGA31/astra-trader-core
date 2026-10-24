#!/usr/bin/env python3
from datetime import datetime, timezone

import fok_shadow_analyzer as fok
import exit_shadow_tournament as exits


def _ms(ts):
    return int(datetime.fromisoformat(ts.replace("Z","+00:00")).timestamp()*1000)


def _bar(ts,o,h,l,c):
    return {
        "open_time_ms":_ms(ts),
        "open":float(o),"high":float(h),"low":float(l),"close":float(c),
        "volume":1.0,
    }


def test_fok_shadow_path_and_r():
    candidate={
        "candidate_id":"fok1",
        "observed_at_utc":"2026-01-01T00:00:10+00:00",
        "asset":"BTC","side":"LONG","strategy_mode":"NORMAL",
        "hypothetical_entry_price":100.0,
        "stop_loss":98.0,
        "take_profit_1":104.0,
        "take_profit_2":106.0,
        "hypothetical_entry_assumption":"PRE_ORDER_EXECUTABLE_TOUCH",
    }
    bars=[
        _bar("2026-01-01T00:01:00Z",100,101,99,100.5),
        _bar("2026-01-01T00:02:00Z",100.5,104.5,100,104),
        _bar("2026-01-01T00:03:00Z",104,106.5,103.5,106),
    ]
    x=fok.evaluate_candidate(candidate,bars,5)
    assert x is not None,x
    assert x["path"]=="TP2_HIT",x
    assert x["positive"] is True,x
    assert x["mfe_r"]>=3.0,x
    assert abs(x["time_exit_r"]-3.0)<1e-9,x


def test_fok_excludes_partial_observation_minute():
    candidate={
        "candidate_id":"fok2",
        "observed_at_utc":"2026-01-01T00:00:30+00:00",
        "asset":"BTC","side":"LONG",
        "hypothetical_entry_price":100.0,
        "stop_loss":98.0,
        "take_profit_1":104.0,
        "take_profit_2":106.0,
    }
    # First bar starts before observation and contains an impossible-to-order
    # stop/target path. It must be excluded from evaluation.
    bars=[
        _bar("2026-01-01T00:00:00Z",100,110,90,100),
        _bar("2026-01-01T00:01:00Z",100,101,99.5,100.5),
    ]
    x=fok.evaluate_candidate(candidate,bars,5)
    assert x["path"]=="TIME_EXIT",x
    assert x["bar_count"]==1,x


def test_exit_tournament_profit_path():
    opened={
        "event":"OKX_POSITION_OPENED",
        "order_id":"ord1",
        "opened_at_utc":"2026-01-01T00:00:10+00:00",
        "asset":"BTC","side":"LONG","strategy_mode":"NORMAL",
        "entry":100.0,"stop_loss":98.0,"take_profit_1":104.0,"take_profit_2":106.0,
    }
    bars=[
        _bar("2026-01-01T00:01:00Z",100,101,99.5,100.5),
        _bar("2026-01-01T00:02:00Z",100.5,104.5,100,104),
        _bar("2026-01-01T00:03:00Z",104,105.5,103.8,105),
        _bar("2026-01-01T00:04:00Z",105,106.5,104,106),
    ]
    x=exits.simulate(opened,bars,5)
    assert x is not None,x
    p={z["policy"]:z for z in x["policies"]}
    assert abs(p["TP1_FULL"]["gross_r"]-2.0)<1e-9,p
    assert abs(p["TP2_FULL"]["gross_r"]-3.0)<1e-9,p
    assert abs(p["80_20_BE_RUNNER"]["gross_r"]-2.2)<1e-9,p
    assert abs(p["50_50_BE_RUNNER"]["gross_r"]-2.5)<1e-9,p
    assert p["TRAIL_AFTER_TP1"]["gross_r"]>2.0,p


def test_exit_tournament_same_bar_is_not_fake_precision():
    opened={
        "event":"OKX_POSITION_OPENED",
        "order_id":"ord2",
        "opened_at_utc":"2026-01-01T00:00:10+00:00",
        "asset":"ETH","side":"LONG",
        "entry":100.0,"stop_loss":98.0,"take_profit_1":104.0,"take_profit_2":106.0,
    }
    bars=[_bar("2026-01-01T00:01:00Z",100,107,97,101)]
    x=exits.simulate(opened,bars,5)
    p={z["policy"]:z for z in x["policies"]}
    assert p["TP1_FULL"]["status"]=="AMBIGUOUS",p
    assert p["TP2_FULL"]["status"]=="AMBIGUOUS",p
    assert p["80_20_BE_RUNNER"]["status"]=="AMBIGUOUS",p


def test_shadow_labs_have_no_authority():
    for module in (fok,exits):
        assert module.ORDER_CAPABILITY is False
        assert module.MODEL_CAPABILITY is False
        assert module.RISK_AUTHORITY is False
        assert module.EXECUTION_AUTHORITY is False


if __name__=="__main__":
    test_fok_shadow_path_and_r()
    test_fok_excludes_partial_observation_minute()
    test_exit_tournament_profit_path()
    test_exit_tournament_same_bar_is_not_fake_precision()
    test_shadow_labs_have_no_authority()
    print({
        "status":"OK",
        "fok_shadow":"PASSIVE",
        "exit_tournament":"PASSIVE",
        "will_open_order":False,
        "will_close_order":False,
        "will_call_model":False,
    })

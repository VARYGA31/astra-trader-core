#!/usr/bin/env python3
"""No-network test: transparent halt diagnosis without relaxing any risk guard."""
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
import config
import trade_cycle
import worker


def ledger(halt=False):
    return {"initial_equity":10000.0,"equity":9200.0,
            "realized_pnl":-800,"daily_pnl":0.0,
            "drawdown_pct":0.08,"trading_halted":halt,"closed_trades":41}


def check(ledger_state,eq_state,latch_state,dd_limit=0.05):
    with patch.object(config,"EXECUTION_MODE","okx_demo"), \
         patch.object(config,"MAX_DRAWDOWN_PCT",dd_limit), \
         patch.object(config,"DAILY_LOSS_LIMIT_PCT",0.003), \
         patch.object(trade_cycle.demo_ledger,"status",return_value=ledger_state), \
         patch.object(trade_cycle.okx_position_monitor,"active_summary",return_value={
             "open_positions":0,"current_exposure_usd":0,"assets":[],"details":[]}), \
         patch.object(trade_cycle.equity_guard,"snapshot",return_value=eq_state), \
         patch.object(trade_cycle.daily_loss_latch,"observe",return_value=latch_state), \
         patch.object(trade_cycle.demo_ledger,"halt_for_mark_to_market_drawdown") as halt:
        state=trade_cycle.account_state()
        return state,halt.call_count


def test_persisted_halt_identified_when_daily_clean():
    l=ledger(halt=True)
    l["equity"]=10000.0
    l["drawdown_pct"]=0
    result,called=check(l,{"verified":True,"equity":10000.0,"daily_pnl":0,"source":"OKX"}, {"latched":False},dd_limit=0.05)
    diag=result["entry_halt_diagnostics"]
    assert result["trading_halted"] and "PERSISTED_LEDGER_HALT" in diag["reasons"],diag
    assert "UTC_DAILY_LOSS_LATCH" not in diag["reasons"],diag
    assert called==0 and diag["conservative_equity_drawdown_pct"]==0,diag


def test_daily_loss_latch_is_separate():
    l=ledger(halt=False)
    l["equity"]=10000.0
    l["drawdown_pct"]=0
    state,called=check(l,{"verified":True,"equity":10000.0,"daily_pnl":-40,"source":"OKX"},
                       {"latched":True,"reason":"DAILY_LOSS_LIMIT_REACHED","date_utc":"2026-10-30"},dd_limit=0.05)
    diag=state["entry_halt_diagnostics"]
    assert diag["reasons"]==["UTC_DAILY_LOSS_LATCH"],diag
    assert diag["daily_loss_latch_reason"]=="DAILY_LOSS_LIMIT_REACHED",diag
    assert called==0,called


def test_live_max_drawdown_still_sticky():
    state,called=check(ledger(halt=False),{"verified":True,"equity":9200.0,"daily_pnl":0},
                       {"latched":False},dd_limit=0.05)
    diag=state["entry_halt_diagnostics"]
    assert state["trading_halted"],diag
    assert "MARK_TO_MARKET_DRAWDOWN_LIMIT" in diag["reasons"],diag
    assert called==1,called


def test_equity_unverified_has_distinct_reason():
    state,called=check(ledger(halt=False),{"verified":False,"reason":"OKX_EQUITY_UNAVAILABLE"},
                       {"latched":True,"reason":"EQUITY_UNVERIFIED"},dd_limit=0.2)
    diag=state["entry_halt_diagnostics"]
    assert state["trading_halted"] and "EQUITY_UNVERIFIED" in diag["reasons"],diag
    assert diag["conservative_equity_drawdown_pct"] is None,diag
    assert called==0,called


def test_healthy_state_does_not_introduce_new_blocks():
    l=ledger(halt=False)
    l["equity"]=10000.0
    l["drawdown_pct"]=0.0
    state,called=check(l,{"verified":True,"equity":10000,"daily_pnl":0,"source":"OKX"},
                       {"latched":False},dd_limit=0.05)
    assert state["trading_halted"] is False,state
    assert state["entry_halt_diagnostics"]["reasons"]==[],state
    assert called==0


def test_news_stats_are_factual_and_read_only():
    when=datetime.now(timezone.utc)
    rows=[
        {"timestamp_utc":(when-timedelta(hours=1)).isoformat(),"asset":"BTC",
         "impact_hint":"HIGH","trade_usable":True},
        {"timestamp_utc":(when-timedelta(hours=2)).isoformat(),"asset":"ETH",
         "impact_hint":"HIGH","trade_usable":False},
        {"timestamp_utc":(when-timedelta(days=3)).isoformat(),"asset":"XAU",
         "impact_hint":"HIGH","trade_usable":True},
    ]
    poll={"status":"OK","polled_at_utc":when.isoformat(),
          "new_events":[{"title":"test"}],
          "high_impact_new":[],
          "health":{"BTC":{"events_returned":3,"high_impact_count":2,"source_successes":4,
                           "source_failures":0,"data_quality":"OK"}}}
    with patch.object(worker.observability,"_load_jsonl",return_value=rows),\
         patch.dict(worker.R,{"last_news":poll}):
        stats=worker._safe_news_pulse()
    assert stats["journal_24h_events"]==2,stats
    assert stats["journal_24h_high_impact"]==2,stats
    assert stats["journal_24h_verified_high_impact"]==1,stats
    assert stats["by_asset_24h"]["BTC"]["high_verified"]==1,stats
    assert stats["news_not_equal_trade_signal"] is True,stats


if __name__=="__main__":
    test_persisted_halt_identified_when_daily_clean()
    test_daily_loss_latch_is_separate()
    test_live_max_drawdown_still_sticky()
    test_equity_unverified_has_distinct_reason()
    test_healthy_state_does_not_introduce_new_blocks()
    test_news_stats_are_factual_and_read_only()
    print("HALT_NEWS_DIAGNOSTICS=PASS; trade_permissions_unchanged=true")

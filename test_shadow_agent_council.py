#!/usr/bin/env python3
import inspect
import tempfile
from pathlib import Path

import agent_council
import market_scanner

def package(asset="BTC",halted=False):
    return {
        "asset":asset,
        "strategy_mode":"NORMAL",
        "guards":{
            "market_ok":True,
            "news_ok":True,
            "critical_news_verified":True,
            "trading_halted":halted,
            "cooldown":{"active":False},
            "loss_streak_pause":{"active":False},
        },
        "decision_context":{
            "market":{
                "data_quality":{"status":"OK"},
                "spot":{
                    "price":100.0,
                    "changes_pct":{"1h":0.55,"4h":1.25,"24h":2.8},
                    "indicators":{"rsi14":61.0,"atr_pct":0.8},
                    "regimes":{"trend":"BULLISH","momentum":"BULLISH"},
                    "order_book":{"imbalance":0.22},
                    "trade_flow":{"buy_sell_ratio":1.35},
                },
                "perp_okx":{
                    "last_price":100.0,
                    "bid_price":99.99,
                    "ask_price":100.01,
                    "funding_rate":0.0001,
                    "open_interest_contracts":123456.0,
                },
                "multi_timeframe":{
                    "status":"OK",
                    "frames":{
                        "15m":{"regimes":{"trend":"BULLISH"},"volume":{"ratio_to_avg20":1.4}},
                        "1h":{"regimes":{"trend":"BULLISH"},"volume":{"ratio_to_avg20":1.3}},
                        "4h":{"regimes":{"trend":"BULLISH"}},
                    },
                },
            },
            "news":{"guard":{"status":"OK"},"events":[]},
        },
    }

def gate():
    return {
        "call_model":True,
        "reason":"MODEL_GATE_PASS",
        "allowed_direction":"LONG",
        "mtf_quality":86,
        "mtf":{"passed":True,"direction":"LONG","quality":86},
    }

def _sandbox():
    td=tempfile.TemporaryDirectory()
    root=Path(td.name)
    old=(market_scanner.STATE,agent_council.STATE,agent_council.LOG,agent_council.OUTCOMES)
    market_scanner.STATE=root/"scanner.json"
    agent_council.STATE=root/"council_state.json"
    agent_council.LOG=root/"council.jsonl"
    agent_council.OUTCOMES=root/"council_outcomes.jsonl"
    return td,old

def _restore(td,old):
    market_scanner.STATE,agent_council.STATE,agent_council.LOG,agent_council.OUTCOMES=old
    td.cleanup()

def test_council_is_strong_but_shadow_only():
    td,old=_sandbox()
    try:
        p=package()
        market_scanner.observe(p)
        x=agent_council.evaluate(p,gate())
        assert x["status"]=="STRONG_CONSENSUS",x
        assert x["target_direction"]=="LONG",x
        assert x["agree_count"]>=4,x
        assert x["order_capability"] is False,x
        assert x["model_call_capability"] is False,x
        assert x["execution_authority"] is False,x
        assert len(x["agents"])==6,x
        agent_council.record(x,p)
        s=agent_council.summary()
        assert s["recorded_total"]==1,s
        assert "BTC" in s["strong_assets"],s
    finally:
        _restore(td,old)

def test_hard_guard_creates_shadow_veto():
    td,old=_sandbox()
    try:
        p=package(halted=True)
        market_scanner.observe(p)
        x=agent_council.evaluate(p,gate())
        assert x["status"]=="VETO",x
        cerberus=next(a for a in x["agents"] if a["agent"]=="CERBERUS")
        assert cerberus["veto"] is True,cerberus
    finally:
        _restore(td,old)

def test_scanner_ranks_without_network_or_execution():
    td,old=_sandbox()
    try:
        market_scanner.observe(package("BTC"))
        eth=package("ETH")
        eth["decision_context"]["market"]["spot"]["changes_pct"]["1h"]=0.1
        eth["decision_context"]["market"]["spot"]["changes_pct"]["4h"]=0.2
        eth["decision_context"]["market"]["spot"]["order_book"]["imbalance"]=0.01
        eth["decision_context"]["market"]["spot"]["trade_flow"]["buy_sell_ratio"]=1.0
        eth["decision_context"]["market"]["multi_timeframe"]["frames"]["15m"]["volume"]["ratio_to_avg20"]=0.8
        market_scanner.observe(eth)
        s=market_scanner.summary()
        assert s["ranking"],s
        assert s["ranking"][0]["asset"]=="BTC",s
        assert s["order_capability"] is False,s
        assert s["model_call_capability"] is False,s
        src=inspect.getsource(market_scanner)
        for forbidden in ("requests.","OpenAI(","execution_router","trade_cycle.execute"):
            assert forbidden not in src,forbidden
    finally:
        _restore(td,old)

if __name__=="__main__":
    test_council_is_strong_but_shadow_only()
    test_hard_guard_creates_shadow_veto()
    test_scanner_ranks_without_network_or_execution()
    print({"status":"OK","council":"SHADOW_ONLY","agents":6,"scanner":"ZERO_TOKEN"})

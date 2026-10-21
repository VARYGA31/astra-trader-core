#!/usr/bin/env python3
import inspect
import tempfile
from pathlib import Path

import astra_client
import config
import model_budget

class Details:
    cached_tokens=100
class Usage:
    input_tokens=1000
    output_tokens=200
    total_tokens=1200
    input_tokens_details=Details()
class Response:
    usage=Usage()

def _sandbox():
    td=tempfile.TemporaryDirectory()
    root=Path(td.name)
    old=(model_budget.USAGE_FILE,model_budget.EVENT_FILE,model_budget.STATE_FILE)
    model_budget.USAGE_FILE=root/"usage.jsonl"
    model_budget.EVENT_FILE=root/"events.jsonl"
    model_budget.STATE_FILE=root/"state.json"
    return td,old

def _restore(td,old):
    model_budget.USAGE_FILE,model_budget.EVENT_FILE,model_budget.STATE_FILE=old
    td.cleanup()

def test_normal_budget_protects_emergency_reserve():
    td,old=_sandbox()
    vals=(config.MODEL_DAILY_MAX_CALLS,config.MODEL_EMERGENCY_RESERVE_CALLS,config.MODEL_DAILY_MAX_USD,config.MODEL_ESTIMATED_NEXT_CALL_USD)
    try:
        config.MODEL_DAILY_MAX_CALLS=3
        config.MODEL_EMERGENCY_RESERVE_CALLS=1
        config.MODEL_DAILY_MAX_USD=10.0
        config.MODEL_ESTIMATED_NEXT_CALL_USD=0.01
        for i in range(2):
            p=model_budget.before_call("TRADE_DECISION",asset="BTC")
            assert p["allowed"],p
            model_budget.record_success(Response(),p["reservation_id"],"TRADE_DECISION",asset="BTC",strategy_mode="NORMAL",model="gpt-6.1-sol")
        blocked=model_budget.before_call("TRADE_DECISION",asset="ETH")
        assert not blocked["allowed"],blocked
        assert blocked["reason"]=="MODEL_EMERGENCY_RESERVE_PROTECTED",blocked
        emergency=model_budget.before_call("EMERGENCY_NEWS_EXIT",asset="BTC",priority="emergency")
        assert emergency["allowed"],emergency
    finally:
        config.MODEL_DAILY_MAX_CALLS,config.MODEL_EMERGENCY_RESERVE_CALLS,config.MODEL_DAILY_MAX_USD,config.MODEL_ESTIMATED_NEXT_CALL_USD=vals
        _restore(td,old)

def test_quota_error_opens_global_circuit():
    td,old=_sandbox()
    old_notify=model_budget._notify_once
    old_retry=config.MODEL_QUOTA_RETRY_SECONDS
    try:
        model_budget._notify_once=lambda *a,**k:None
        config.MODEL_QUOTA_RETRY_SECONDS=1800
        p=model_budget.before_call("TRADE_DECISION",asset="CRV")
        assert p["allowed"],p
        info=model_budget.record_error(
            Exception("429 insufficient_quota credit_balance_exhausted: no credits remaining"),
            p["reservation_id"],"TRADE_DECISION",asset="CRV",model="gpt-6.1-sol"
        )
        assert info["kind"]=="CREDIT_EXHAUSTED",info
        s=model_budget.summary()
        assert s["status"]=="OFFLINE_QUOTA",s
        q=model_budget.before_call("TRADE_DECISION",asset="XAU")
        assert not q["allowed"],q
        assert q["reason"]=="MODEL_CIRCUIT_OPEN",q
    finally:
        model_budget._notify_once=old_notify
        config.MODEL_QUOTA_RETRY_SECONDS=old_retry
        _restore(td,old)

def test_trade_client_is_cost_bounded():
    src=inspect.getsource(astra_client.decide)
    assert "model_budget.before_call" in src,src
    assert "max_output_tokens" in src,src
    assert "Apply this strategy policy exactly" not in src,src
    assert config.MODEL_MAX_OUTPUT_TOKENS<=1000,config.MODEL_MAX_OUTPUT_TOKENS

if __name__=="__main__":
    test_normal_budget_protects_emergency_reserve()
    test_quota_error_opens_global_circuit()
    test_trade_client_is_cost_bounded()
    print({"status":"OK","model_budget":"UNIFIED","circuit":"FAIL_CLOSED"})

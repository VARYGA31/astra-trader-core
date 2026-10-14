#!/usr/bin/env python3
"""Pure local test: no OpenAI, no OKX, no orders."""
import json,sys,types
# Stub OpenAI import: this test never calls the network/model.
m=types.ModuleType("openai")
m.OpenAI=object
sys.modules.setdefault("openai",m)
import astra_client

assert "WAIT is an exception, not the default" in astra_client.DECISION_POLICY
assert "Do NOT WAIT merely because a pullback/retest might be nicer" in astra_client.DECISION_POLICY
assert "TRANSITION remains conservative" in astra_client.DECISION_POLICY

pkg={"asset":"GRAM","timeframe":"1h"}
trade=astra_client._normalize_decision({
    "asset":"GRAM","action":"SHORT","confidence":0.88,
    "setup_type":"PULLBACK_CONTINUATION","wait_category":"CHASE_RISK",
    "wait_is_hard_blocker":True,
    "entry":1.37,"stop_loss":1.39,"take_profit_1":1.34,"take_profit_2":1.32,
},pkg)
assert trade["action"]=="SHORT"
assert trade["confidence"]==88.0
assert trade["wait_category"]=="NONE"
assert trade["wait_is_hard_blocker"] is False
assert trade["decision_policy_version"]=="normal_cal_v1"

hard_wait=astra_client._normalize_decision({
    "asset":"ETH","action":"WAIT","confidence":87,
    "setup_type":"NONE","wait_category":"REVERSAL_RISK",
    "wait_is_hard_blocker":True,"reason":"concrete reversal evidence"
},{"asset":"ETH"})
assert hard_wait["action"]=="WAIT"
assert hard_wait["wait_category"]=="REVERSAL_RISK"
assert hard_wait["wait_is_hard_blocker"] is True
assert hard_wait["entry"] is None

soft_wait=astra_client._normalize_decision({
    "asset":"GRAM","action":"WAIT","confidence":90,
    "wait_category":"RETEST_PREFERENCE","wait_is_hard_blocker":False,
},{"asset":"GRAM"})
# Safety invariant: code never auto-converts WAIT into a trade.
assert soft_wait["action"]=="WAIT"
assert soft_wait["wait_category"]=="UNSPECIFIED"
assert soft_wait["wait_is_hard_blocker"] is False

print(json.dumps({
    "status":"OK",
    "will_open_order":False,
    "will_close_order":False,
    "will_call_model":False,
    "policy_version":"normal_cal_v1",
    "normal_wait_is_exception":True,
    "transition_stays_strict":True,
    "soft_wait_never_auto_converted":True,
    "diagnostics_added":["wait_category","wait_is_hard_blocker","model_wait_categories"]
},ensure_ascii=False,indent=2))

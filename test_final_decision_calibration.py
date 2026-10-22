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

# Immediate FOK entries are deterministic: the model may omit or hallucinate
# entry, but Python anchors the actionable decision to the OKX perp snapshot.
uni_pkg={
    "asset":"UNI","strategy_mode":"NORMAL",
    "decision_context":{"market":{"perp_okx":{"last_price":"7.025"}}},
}
uni=astra_client._normalize_decision({
    "asset":"UNI","action":"LONG","confidence":91,
    "entry":None,"stop_loss":6.95,"take_profit_1":7.15,"take_profit_2":7.25,
    "setup_type":"TREND_CONTINUATION",
},uni_pkg)
assert uni["entry"]==7.025,uni
assert uni["model_entry_raw"] is None,uni
assert uni["entry_reference_source"]=="OKX_PERP_SNAPSHOT",uni

xau_pkg={
    "asset":"XAU","strategy_mode":"NORMAL",
    "decision_context":{"market":{"perp_okx":{"last_price":"4118.5"}}},
}
xau=astra_client._normalize_decision({
    "asset":"XAU","action":"SHORT","confidence":90,
    "entry":3999.0,"stop_loss":4140.0,"take_profit_1":4080.0,"take_profit_2":4050.0,
    "setup_type":"TREND_CONTINUATION",
},xau_pkg)
assert xau["entry"]==4118.5,xau
assert xau["model_entry_raw"]==3999.0,xau
assert xau["entry_reference_source"]=="OKX_PERP_SNAPSHOT",xau

compact=astra_client._compact(uni_pkg)
assert compact["decision_policy"]["defi_min_trade_confidence"]==astra_client.config.DEFI_TRADE_MIN_CONFIDENCE
assert compact["decision_policy"]["asset_min_trade_confidence"]==astra_client.config.DEFI_TRADE_MIN_CONFIDENCE

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

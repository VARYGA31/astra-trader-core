#!/usr/bin/env python3
import config
import mission_control

def test_mission_control_is_read_only():
    html=mission_control.html()
    assert "ASTRA · MISSION CONTROL" in html
    assert "READ ONLY" in html
    assert "/api/mission-control" in html
    for forbidden in ("/trade","/order","/leverage","/risk-update","open_fok"):
        assert forbidden not in html,forbidden

def test_payload_contains_safe_research_layers():
    runtime={
        "status":"ok",
        "execution_mode":"okx_demo",
        "decision_engine_enabled":True,
        "trade_execution_enabled":True,
        "strategy_mode":{"mode":"NORMAL"},
        "micro_stream":{"status":"RUNNING","connected":True},
        "crypto_shadow_lab":{"status":"OK"},
        "skip_reasons":{"MTF_NOT_ALIGNED":12},
        "last_decisions":{},
    }
    x=mission_control.build_payload(runtime)
    assert x["read_only"] is True,x
    assert x["system"]["mode"]=="NORMAL",x
    assert "alpha_factory" in x["research"],x
    assert "tournament" in x["research"],x
    assert "normal_assets" in x["universe"],x
    assert "model_budget" in x,x
    assert "status" in x["model_budget"],x

if __name__=="__main__":
    test_mission_control_is_read_only()
    test_payload_contains_safe_research_layers()
    print({"status":"OK","mission_control":"READ_ONLY"})

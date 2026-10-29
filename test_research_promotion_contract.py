#!/usr/bin/env python3
"""No-order test: repeated backtests can NEVER auto-promote trade strategies."""
import copy
import research_promotion_contract as contract


def m(n,avg,pf,stress_avg=None,stress_pf=None):
    return {"trades":n,"avg_net_r":avg,"profit_factor":pf,
            "stress_avg_net_r":stress_avg,"stress_profit_factor":stress_pf,
            "max_drawdown_r":3}


def sample():
    return {
        "status":"RESEARCH_ONLY","orders_possible":False,
        "data_source":"OKX_PUBLIC_CONFIRMED_SWAP_CANDLES_NOT_DEMO",
        "split":"chronological_70pct_development_30pct_validation",
        "data_errors":{},"assumed_roundtrip_friction_pct":0.14,
        "stress_roundtrip_friction_pct":0.24,
        "predeclared_rules":{"compression_breakout":"fixed rules"},
        "assets":{"AAVE":{"strategies":{
            "normal":{"development":m(100,-0.1,0.8),"validation":m(80,-0.2,0.7)},
            "compression_breakout":{
                "development":m(100,0.12,1.3),
                "validation":m(35,0.10,1.30,0.025,1.12),
            },
        }}},
    }


def test_even_strong_oos_never_promotes_or_trades():
    out=contract.assess_report(sample())
    assert out["status"]=="SHADOW_CANDIDATES_ONLY",out
    assert out["order_authority"] is False and out["automatic_promotion"] is False,out
    assert out["evaluations"][0]["status"]=="REQUIRES_NEW_FORWARD_SHADOW",out
    assert out["evaluations"][0]["may_place_orders"] is False,out
    assert out["evaluations"][0]["may_disable_existing_assets_or_setups"] is False,out


def test_29_validation_trades_not_enough():
    report=sample()
    report["assets"]["AAVE"]["strategies"]["compression_breakout"]["validation"]["trades"]=29
    result=contract.assess_report(report)
    assert result["status"]=="NO_VALIDATED_RESEARCH_EDGE",result
    assert "INSUFFICIENT_VALIDATION_TRADES" in result["evaluations"][0]["blockers"],result


def test_aave_weak_stress_does_not_pass():
    report=sample()
    report["assets"]["AAVE"]["strategies"]["compression_breakout"]["validation"].update(
        {"stress_avg_net_r":-0.028,"stress_profit_factor":0.96}
    )
    result=contract.assess_report(report)
    assert "NOT_ROBUST_TO_HIGHER_COSTS" in result["evaluations"][0]["blockers"],result
    assert not result["forward_shadow_candidates"],result


def test_partial_inputs_missing_costs_predeclared_or_provenance_fail_closed():
    for field,value in [
        ("status","PARTIAL"),
        ("orders_possible",True),
        ("data_errors",{"BTC":"FAILED"}),
        ("split","IN_SAMPLE_ONLY"),
        ("assumed_roundtrip_friction_pct",0.0),
        ("stress_roundtrip_friction_pct",0.14),
    ]:
        report=sample()
        report[field]=value
        result=contract.assess_report(report)
        assert result["status"]=="INVALID_RESEARCH",(field,result)
        assert result["automatic_promotion"] is False,result


def test_missing_rule_train_or_baseline_cannot_qualify():
    variants=[]
    x=sample();x["predeclared_rules"]={};variants.append(x)
    x=sample();x["assets"]["AAVE"]["strategies"]["compression_breakout"]["development"]["avg_net_r"]=-0.05;variants.append(x)
    x=sample();x["assets"]["AAVE"]["strategies"]["normal"]["validation"]["avg_net_r"]=0.2;variants.append(x)
    for report in variants:
        result=contract.assess_report(report)
        assert result["status"]=="NO_VALIDATED_RESEARCH_EDGE",result
        assert result["evaluations"][0]["blockers"],result


def test_invalid_or_empty_reports_fail_closed():
    for report in (None,{},{"status":"RESEARCH_ONLY"}):
        result=contract.assess_report(report)
        assert result["status"]=="INVALID_RESEARCH",result
        assert result["order_authority"] is False,result


if __name__=="__main__":
    test_even_strong_oos_never_promotes_or_trades()
    test_29_validation_trades_not_enough()
    test_aave_weak_stress_does_not_pass()
    test_partial_inputs_missing_costs_predeclared_or_provenance_fail_closed()
    test_missing_rule_train_or_baseline_cannot_qualify()
    test_invalid_or_empty_reports_fail_closed()
    print("RESEARCH_PROMOTION_CONTRACT=PASS; automatic_promotions=0")

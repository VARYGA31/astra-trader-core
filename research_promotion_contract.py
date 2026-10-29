#!/usr/bin/env python3
"""Mechanical review of ASTRA research claims (zero order authority).

Prevents a profitable-looking *development* window, raw/unpriced returns or
one lucky OOS window from being described as a deployable strategy. This
module does not optimize rules, re-run research, touch Railway, or change any
ASTRA trading permission. Passing is only permission to STUDY FORWARD SHADOW.
"""
import argparse
import json
import math
from pathlib import Path

MIN_DEVELOPMENT_TRADES=30
MIN_VALIDATION_TRADES=30
MIN_BASE_PROFIT_FACTOR=1.10
MIN_STRESS_PROFIT_FACTOR=1.10
MIN_COST_PCT=0.14
MIN_STRESS_COST_PCT=0.24


def _finite(value):
    try:
        n=float(value)
        return n if math.isfinite(n) else None
    except (ValueError,TypeError):
        return None


def _strong(metrics, stressed=False):
    if not isinstance(metrics,dict):
        return False
    n=_finite(metrics.get("trades"))
    expectancy=_finite(metrics.get("stress_avg_net_r" if stressed else "avg_net_r"))
    pf=_finite(metrics.get("stress_profit_factor" if stressed else "profit_factor"))
    return bool(n is not None and n>=MIN_VALIDATION_TRADES
                and expectancy is not None and expectancy>0
                and pf is not None and pf>=(
                    MIN_STRESS_PROFIT_FACTOR if stressed else MIN_BASE_PROFIT_FACTOR
                ))


def assess_report(report):
    if not isinstance(report,dict):
        return {"status":"INVALID_RESEARCH","reason":"REPORT_NOT_OBJECT",
                "order_authority":False,"automatic_promotion":False}
    clean=(
        report.get("status")=="RESEARCH_ONLY"
        and report.get("orders_possible") is False
        and report.get("data_source")=="OKX_PUBLIC_CONFIRMED_SWAP_CANDLES_NOT_DEMO"
        and report.get("split")=="chronological_70pct_development_30pct_validation"
        and not (report.get("data_errors") or {})
        and isinstance(report.get("predeclared_rules"),dict)
        and _finite(report.get("assumed_roundtrip_friction_pct")) is not None
        and _finite(report.get("stress_roundtrip_friction_pct")) is not None
        and float(report["assumed_roundtrip_friction_pct"])>=MIN_COST_PCT
        and float(report["stress_roundtrip_friction_pct"])>=MIN_STRESS_COST_PCT
    )
    if not clean:
        return {"status":"INVALID_RESEARCH",
                "reason":"MISSING_OR_UNTRUSTED_RESEARCH_PROVENANCE_COSTS_OR_SPLIT",
                "order_authority":False,"automatic_promotion":False,
                "next_step":"REPAIR_RESEARCH_DATA_AND_RERUN"}
    out=[]
    assets=report.get("assets") or {}
    if not isinstance(assets,dict) or not assets:
        return {"status":"INVALID_RESEARCH","reason":"NO_ASSET_EVIDENCE",
                "order_authority":False,"automatic_promotion":False}
    for asset,detail in sorted(assets.items()):
        stats=detail.get("strategies") if isinstance(detail,dict) else {}
        stats=stats if isinstance(stats,dict) else {}
        normal=stats.get("normal") or {}
        baseline=(normal.get("validation") or {}) if isinstance(normal,dict) else {}
        baseline_avg=_finite(baseline.get("avg_net_r"))
        for strategy,windows in sorted(stats.items()):
            if strategy=="normal":
                continue
            reasons=[]
            if strategy not in report["predeclared_rules"]:
                reasons.append("RULES_NOT_PREDECLARED")
            train=windows.get("development") if isinstance(windows,dict) else None
            validation=windows.get("validation") if isinstance(windows,dict) else None
            if not isinstance(train,dict) or not isinstance(validation,dict):
                reasons.append("MISSING_CHRONOLOGICAL_WINDOWS")
                train,validation=train or {},validation or {}
            train_n=_finite(train.get("trades")) if isinstance(train,dict) else None
            val_n=_finite(validation.get("trades")) if isinstance(validation,dict) else None
            if train_n is None or train_n<MIN_DEVELOPMENT_TRADES:
                reasons.append("INSUFFICIENT_DEVELOPMENT_TRADES")
            if val_n is None or val_n<MIN_VALIDATION_TRADES:
                reasons.append("INSUFFICIENT_VALIDATION_TRADES")
            if not _strong(validation):
                reasons.append("NO_POSITIVE_NET_OUT_OF_SAMPLE_EDGE")
            if not _strong(validation,stressed=True):
                reasons.append("NOT_ROBUST_TO_HIGHER_COSTS")
            if (baseline_avg is None
                or _finite(validation.get("avg_net_r")) is None
                or float(validation["avg_net_r"])<=baseline_avg):
                reasons.append("NO_MEASURED_IMPROVEMENT_VS_SAME_ASSET_BASELINE")
            if (not isinstance(train,dict)
                or _finite(train.get("avg_net_r")) is None
                or float(train["avg_net_r"])<=0):
                reasons.append("DEVELOPMENT_EDGE_NOT_REPRODUCED")
            # Trade histories have been examined repeatedly across workflows:
            # even a pass is NOT a fresh or immutable independent holdout.
            result="REQUIRES_NEW_FORWARD_SHADOW" if not reasons else "RESEARCH_ONLY_REJECTED"
            out.append({
                "asset":str(asset).upper(),
                "strategy":str(strategy),
                "status":result,
                "blockers":reasons,
                "development_trades":train_n,
                "validation_trades":val_n,
                "validation_avg_net_r":_finite(validation.get("avg_net_r")),
                "validation_stress_avg_net_r":_finite(validation.get("stress_avg_net_r")),
                "baseline_validation_avg_net_r":baseline_avg,
                "may_place_orders":False,
                "may_disable_existing_assets_or_setups":False,
            })
    candidates=[x for x in out if x["status"]=="REQUIRES_NEW_FORWARD_SHADOW"]
    return {
        "status":"SHADOW_CANDIDATES_ONLY" if candidates else "NO_VALIDATED_RESEARCH_EDGE",
        "order_authority":False,"automatic_promotion":False,
        "inspected_assets":sorted(str(x).upper() for x in assets),
        "strategies_checked":len(out),
        "forward_shadow_candidates":[{"asset":x["asset"],"strategy":x["strategy"]} for x in candidates],
        "evaluations":out,
        "promotion_policy":"Even after passing repeated historical OOS tests, forward NEW shadow data and later limited demo verification are mandatory; never auto-promote.",
        "scope":"Research evidence only; no live entry/risk/asset configuration changes.",
    }


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",required=True)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    try:
        report=json.loads(Path(args.input).read_text(encoding="utf-8"))
    except (OSError,ValueError) as err:
        report={"status":"INPUT_ERROR","error_type":type(err).__name__}
    assessment=assess_report(report)
    Path(args.output).write_text(
        json.dumps(assessment,ensure_ascii=False,indent=2),encoding="utf-8"
    )
    print("ASTRA_RESEARCH_PROMOTION_CHECK="+json.dumps({
        "status":assessment["status"],
        "strategies_checked":assessment.get("strategies_checked",0),
        "shadow_candidates":assessment.get("forward_shadow_candidates",[]),
        "order_authority":False,
    },ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()

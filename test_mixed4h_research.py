#!/usr/bin/env python3
"""No-order, deterministic regressions for read-only MIXED 4H research."""
from datetime import datetime, timezone
import json
import mixed4h_research


NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)


def setup(sid, trend="MIXED", volume=1.0, asset="BTC", candle=1,
          trigger=True, one_h=True, quality=80, legacy=False):
    row = {
        "setup_id": sid, "timestamp_utc": "2026-10-28T08:00:00+00:00",
        "mtf_replay_version": 1, "blocked_reason": "MTF_NOT_ALIGNED",
        "asset": asset, "direction": "LONG", "strategy_mode": "NORMAL",
        "trigger_candle_id": candle, "quality": quality,
        "regime_4h_ok": False, "setup_1h_ok": one_h,
        "trigger_15m_confirmed": trigger, "trigger_15m_count": 4,
        "mtf_blockers": ["4H_REGIME_NOT_ALIGNED"],
        "minimum_quality": 78 if asset == "XAU" else 72,
    }
    if not legacy:
        row.update(trend_4h=trend, volume_ratio_15m=volume)
    return row


def result(sid, return_pct, horizon=60):
    return {"setup_id": sid, "signed_return_pct": return_pct,
            "horizon_minutes": horizon, "mtf_replay_version": 1}


def test_exact_isolated_from_legacy_and_invalid_setups():
    setups = [
        setup("exact", candle=1),
        setup("legacy", candle=2, legacy=True),
        setup("opposite", candle=3, trend="BEARISH"),
        setup("thin", candle=4, volume=0.74),
        setup("weak_1h", candle=5, one_h=False),
        setup("low_quality", candle=6, quality=60),
        setup("xau", candle=7, asset="XAU", quality=75),
        setup("no_trigger", candle=8, trigger=False),
    ]
    outcomes = [result(x["setup_id"], 0.30) for x in setups]
    outcomes += [result("exact", 0.30)]  # Never double-count a horizon.
    report = mixed4h_research.analyze(setups, outcomes, now=NOW)
    assert report["status"] == "OK" and report["read_only"] is True, report
    assert report["roundtrip_cost_assumption_pct"] == 0.14, report
    exact = report["cohorts"]["strict_mixed_4h"]
    legacy = report["cohorts"]["legacy_broad_proxy"]
    assert exact["eligible_setups"] == 1, report
    assert exact["results_by_horizon"]["60"]["samples"] == 1, report
    assert exact["results_by_horizon"]["60"]["mean_net_markout_pct"] == 0.16, report
    assert legacy["eligible_setups"] == 1, report
    assert legacy["results_by_horizon"]["60"]["samples"] == 1, report
    assert exact["results_by_horizon"]["240"]["samples"] == 0, report


def test_old_rows_cannot_be_called_exact_mixed():
    setups = [setup("old", legacy=True, candle=10)]
    report = mixed4h_research.analyze(setups, [result("old", -0.5)], now=NOW)
    assert report["cohorts"]["strict_mixed_4h"]["eligible_setups"] == 0, report
    assert report["cohorts"]["legacy_broad_proxy"]["results_by_horizon"]["60"]["mean_net_markout_pct"] == -0.64, report


def test_dedup_same_candle_and_outside_window():
    a = setup("first", candle=100)
    b = setup("second", candle=100)
    old = setup("old", candle=101)
    old["timestamp_utc"] = "2026-09-01T08:00:00+00:00"
    report = mixed4h_research.analyze([a,b,old],
             [result("first",0.5),result("second",1),result("old",100)],
             now=NOW)
    assert report["cohorts"]["strict_mixed_4h"]["eligible_setups"] == 1, report
    assert report["cohorts"]["strict_mixed_4h"]["results_by_horizon"]["60"]["samples"] == 1, report


if __name__ == "__main__":
    test_exact_isolated_from_legacy_and_invalid_setups()
    test_old_rows_cannot_be_called_exact_mixed()
    test_dedup_same_candle_and_outside_window()
    print(json.dumps({"status":"OK","trade_authority":False,
                      "tested":"MIXED_4H_PROBE_STRICT_AND_LEGACY"},indent=2))

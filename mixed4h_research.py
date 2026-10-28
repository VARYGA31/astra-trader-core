#!/usr/bin/env python3
"""Read-only audit of a hypothetical 4H MIXED entry gate.

NEVER submits orders, invokes LLM, alters risk, or influences decisions.
Only measures directional markouts on independently recorded blocked setups.
"""
import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import config


def _ts(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _number(value):
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (ValueError, TypeError):
        return None


def _metrics(rows, estimated_roundtrip_cost_pct):
    """Each row is (setup_timestamp, signed_price_markout_pct)."""
    if not rows:
        return {"samples": 0}
    ordered = sorted(rows, key=lambda row: row[0])
    vals = [x[1] - estimated_roundtrip_cost_pct for x in ordered]
    result = {
        "samples": len(vals),
        "mean_net_markout_pct": round(statistics.mean(vals), 6),
        "median_net_markout_pct": round(statistics.median(vals), 6),
        "positive_after_cost_pct": round(100 * sum(x > 0 for x in vals) / len(vals), 2),
    }
    # Chronologically last 30%: descriptive OOS-style split only, not an
    # independent locked holdout, because the candidate rule was chosen later.
    if len(vals) >= 20:
        split = max(1, int(len(vals) * 0.70))
        subset = vals[split:]
        result["latest_30pct"] = {
            "samples": len(subset),
            "mean_net_markout_pct": round(statistics.mean(subset), 6),
            "positive_after_cost_pct": round(100 * sum(x > 0 for x in subset) / len(subset), 2),
        }
    return result


def analyze(setups, outcomes, hours=168, now=None, taker_fee_pct_per_side=0.05,
            slippage_pct_per_side=0.02):
    """Pure analysis. Older rows lack 4H trend / 15m exact volume metadata.

    In that case produce a SEPARATE broad legacy proxy, never mislabel it
    as the exact MIXED-4H hypothesis. Only one setup per asset+15m bar+side
    and one markout per setup+horizon are counted.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    cost = 2 * (float(taker_fee_pct_per_side) + float(slippage_pct_per_side))
    if not math.isfinite(cost) or cost < 0:
        raise ValueError("invalid cost assumption")

    known = {}
    by_setup = {}
    for row in setups:
        if str(row.get("blocked_reason")) != "MTF_NOT_ALIGNED":
            continue
        if str(row.get("strategy_mode") or "NORMAL").upper() != "NORMAL":
            continue
        timestamp = _ts(row.get("timestamp_utc"))
        if not timestamp or not cutoff <= timestamp <= now:
            continue
        asset = str(row.get("asset") or "").upper()
        direction = str(row.get("direction") or "").upper()
        if direction not in {"LONG", "SHORT"}:
            continue
        candle = row.get("trigger_candle_id")
        if candle is None:
            continue
        key = (asset, str(candle), direction)
        if key in known:
            continue
        known[key] = True
        # Only consider candidates where the existing MTF gate rejected
        # the 4H regime. Do not loosen setup, trigger or quality.
        blockers = set(row.get("mtf_blockers") or [])
        threshold = _number(row.get("minimum_quality"))
        if threshold is None:
            threshold = float(config.XAU_MTF_MIN_QUALITY if asset == "XAU" else config.MTF_MIN_QUALITY)
        quality = _number(row.get("quality"))
        if not (
            row.get("regime_4h_ok") is False
            and row.get("setup_1h_ok") is True
            and row.get("trigger_15m_confirmed") is True
            and int(row.get("trigger_15m_count") or 0) >= 4
            and "4H_REGIME_NOT_ALIGNED" in blockers
            and blockers.issubset({"4H_REGIME_NOT_ALIGNED"})
            and quality is not None and quality >= threshold
        ):
            continue
        trend = row.get("trend_4h")
        vol = _number(row.get("volume_ratio_15m"))
        if trend == "MIXED" and vol is not None and vol >= 0.90:
            cohort = "strict_mixed_4h"
        elif trend is None or vol is None:
            # May include opposite-trend 4H or 15m volume 0.70-0.89.
            cohort = "legacy_broad_proxy"
        else:
            continue
        setup_id = str(row.get("setup_id") or "")
        if setup_id:
            by_setup[setup_id] = (cohort, timestamp, asset)

    groups = {"strict_mixed_4h": defaultdict(list),
              "legacy_broad_proxy": defaultdict(list)}
    unique = set()
    for outcome in outcomes:
        setup_id = str(outcome.get("setup_id") or "")
        if setup_id not in by_setup:
            continue
        horizon = _number(outcome.get("horizon_minutes"))
        signed = _number(outcome.get("signed_return_pct"))
        if horizon not in (60.0, 240.0) or signed is None:
            continue
        pair = (setup_id, int(horizon))
        if pair in unique:
            continue
        unique.add(pair)
        cohort, ts, asset = by_setup[setup_id]
        groups[cohort][str(int(horizon))].append((ts, signed))

    cohorts = {}
    for cohort in groups:
        sample_setups = [v for v in by_setup.values() if v[0] == cohort]
        cohorts[cohort] = {
            "eligible_setups": len(sample_setups),
            "results_by_horizon": {
                h: _metrics(groups[cohort].get(h, []), cost) for h in ("60", "240")
            },
        }
    return {
        "status": "OK",
        "read_only": True,
        "window_hours": hours,
        "roundtrip_cost_assumption_pct": round(cost, 4),
        "filter": "4H MIXED (not already approved); 1H confirmed; 15m trigger >=4; volume >=0.90; original quality min unchanged",
        "cohorts": cohorts,
        "cautions": "Price markouts only, NOT executable backtest: no stops, TP, FOK, LLM, funding; legacy proxy is not exact MIXED; samples may be correlated.",
    }


def summary(hours=168):
    import observability
    return analyze(
        observability._load_jsonl(observability.SHADOW),
        observability._load_jsonl(observability.SHADOW_OUTCOMES),
        hours=hours,
        taker_fee_pct_per_side=config.TRAINER_TAKER_FEE_PCT_PER_SIDE,
        slippage_pct_per_side=config.TRAINER_SLIPPAGE_PCT_PER_SIDE,
    )

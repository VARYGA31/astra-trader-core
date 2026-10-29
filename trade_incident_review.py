#!/usr/bin/env python3
"""Read-only post-trade incident evidence, not an entry/exit policy.

Summarizes recorded OKX demo outcomes WITHOUT claiming to know why a stop
filled beyond its planned trigger. Only OKX historical algo+fill evidence can
establish actual trigger, broker behavior, or matching order IDs.
No network, no API keys, no orders, no model calls, no asset blacklists.
"""
import hashlib
import math
from datetime import datetime


def _number(value):
    try:
        value=float(value)
        return value if math.isfinite(value) else None
    except (TypeError,ValueError):
        return None


def _rounded(value, digits=5):
    return round(value,digits) if value is not None and math.isfinite(value) else None


def _duration_minutes(start,end):
    try:
        a=datetime.fromisoformat(str(start).replace("Z","+00:00"))
        b=datetime.fromisoformat(str(end).replace("Z","+00:00"))
        if a.tzinfo is None or b.tzinfo is None:
            return None
        d=(b-a).total_seconds()/60
        return _rounded(d,2) if d>=0 else None
    except (ValueError,TypeError,OverflowError):
        return None


def review_trade(row):
    """Create an auditable *observation*. No post-hoc causal attribution."""
    if not isinstance(row,dict):
        return None
    pnl=_number(row.get("pnl_usd"))
    if pnl is None:
        return None
    asset=str(row.get("asset") or "UNKNOWN").upper()
    side=str(row.get("side") or "").upper()
    entry=_number(row.get("entry"))
    stop=_number(row.get("stop_loss"))
    close=_number(row.get("exit_price"))
    notional=_number(row.get("notional_usd"))
    has_geometry=(side in {"LONG","SHORT"} and entry is not None
                  and stop is not None and close is not None
                  and entry>0 and stop>0 and close>0)
    direction=1 if side=="LONG" else -1
    planned_risk_px=(entry-stop)*direction if has_geometry else None
    if planned_risk_px is not None and planned_risk_px<=0:
        has_geometry=False
    risk_usd=(notional*planned_risk_px/entry
              if has_geometry and notional is not None and notional>0
              else None)
    adverse_stop_px=max(0.0,(stop-close)*direction) if has_geometry else None
    adverse_stop_r=(adverse_stop_px/planned_risk_px
                    if has_geometry and planned_risk_px>0 else None)
    stop_overrun=bool(adverse_stop_px is not None and adverse_stop_px>1e-9)
    # This is an indicative comparison of two prices, NOT verified fill slippage
    # or a proof that the exchange actually triggered the intended SL order.
    gross=_number(row.get("gross_pnl_usd"))
    gap=(gross-pnl) if gross is not None else None
    observed_costs={
        "gross_pnl_usd":_rounded(gross,6),
        "net_pnl_usd":_rounded(pnl,6),
        "gross_minus_net_usd":_rounded(gap,6),
        "exchange_fee_field_usd":_rounded(_number(row.get("fee_usd")),6),
        "funding_fee_field_usd":_rounded(_number(row.get("funding_fee_usd")),6),
        "liquidation_penalty_field_usd":_rounded(_number(row.get("liq_penalty_usd")),6),
        "note":"OKX fee and funding fields retain exchange signs; do not subtract them again from realizedPnl",
    }
    tags=[]
    if pnl<0:
        tags.append("REALIZED_LOSS")
    if stop_overrun:
        tags.append("EXIT_PRICE_BEYOND_PLANNED_STOP")
    if pnl<0 and not has_geometry:
        tags.append("RISK_GEOMETRY_UNVERIFIED")
    if bool(row.get("tp1_taken")):
        tags.append("PARTIAL_EXIT_PATH_NEEDS_FILLS")
    reason=str(row.get("reason") or "UNKNOWN")
    if reason in {"STOP_LOSS","TAKE_PROFIT_1","TAKE_PROFIT_2","EXCHANGE_CLOSE"}:
        tags.append("CLOSE_REASON_INFERRED_FROM_PRICE")
    if stop_overrun:
        next_checks=[
            "OKX_EXCHANGE_ORDER_AND_ALGO_HISTORY",
            "SL_TRIGGER_PRICE_TYPE_AND_MARK_INDEX_LAST_AT_TRIGGER",
            "CLOSE_FILLS_AND_PARTIAL_FILLS_WITH_TIMESTAMPS",
        ]
    elif pnl<0:
        next_checks=[
            "REVIEW_ASOF_4H_1H_15M_SIGNAL_AND_REGIME",
            "COMPARE_SAME_SETUP_OUTCOMES_ON_UNSEEN_DATA",
        ]
    else:
        next_checks=[]
    if pnl<0 and gap is None:
        next_checks.append("RETRIEVE_EXCHANGE_GROSS_FEES_FUNDING_BREAKDOWN")
    reference=(str(row.get("close_event_id") or "")
               or "|".join(str(row.get(k) or "") for k in (
                   "asset","order_id","opened_at_utc","timestamp_utc","exit_price")))
    incident_id=hashlib.sha256(reference.encode("utf-8")).hexdigest()[:16]
    return {
        "incident_id":incident_id,
        "asset":asset,
        "side":side or "UNKNOWN",
        "strategy_mode":str(row.get("strategy_mode") or "UNKNOWN").upper(),
        "setup_type":str(row.get("setup_type") or "UNKNOWN").upper(),
        "volatility_regime":row.get("volatility_regime"),
        "opened_at_utc":row.get("opened_at_utc"),
        "closed_at_utc":row.get("timestamp_utc"),
        "duration_minutes":_duration_minutes(row.get("opened_at_utc"),row.get("timestamp_utc")),
        "reported_close_reason":reason,
        "close_reason_verified_by_exchange":False,
        "decision_context":{
            "source":row.get("decision_source"),
            "confidence":row.get("confidence"),
            "mtf_quality":row.get("mtf_quality"),
            "entry_fill_slippage_pct":row.get("fill_slippage_pct"),
        },
        "price_evidence":{
            "entry":_rounded(entry),
            "planned_stop":_rounded(stop),
            "exchange_history_close_avg":_rounded(close),
            "planned_risk_usd_approx":_rounded(risk_usd,6),
            "net_realized_r_approx":_rounded(pnl/risk_usd,4) if risk_usd else None,
            "adverse_price_beyond_stop_r":_rounded(adverse_stop_r,4),
            "adverse_price_beyond_stop_pct":_rounded(100*adverse_stop_px/stop,5) if has_geometry else None,
            "notional_basis_note":"original entry notional; price overshoot is indicative, especially after partial exits",
        },
        "cost_evidence":observed_costs,
        "tags":tags,
        "next_evidence_checks":next_checks,
        "cause":"UNDETERMINED",
        "severity":"EXECUTION_REVIEW" if stop_overrun else "SETUP_REVIEW" if pnl<0 else "OBSERVE",
        "may_change_trade_routing":False,
        "may_blacklist_asset":False,
    }


def summarize(closed_trades, limit=5):
    """Input is the DEDUPED closed-trade journal, not just a recent 24h slice."""
    reviews=[review_trade(t) for t in (closed_trades or [])]
    reviews=[r for r in reviews if r]
    issues=[r for r in reviews if r["severity"]!="OBSERVE"]
    # Use journal order; no selecting only cases with impressive hindsight PnL.
    return {
        "status":"NEEDS_REVIEW" if issues else "NO_RECORDED_LOSS_INCIDENTS",
        "read_only":True,"order_capability":False,
        "automatic_strategy_or_asset_changes":False,
        "closed_trades_evaluated":len(reviews),
        "losing_trades":sum("REALIZED_LOSS" in x["tags"] for x in reviews),
        "exit_price_beyond_planned_stop":sum(
            "EXIT_PRICE_BEYOND_PLANNED_STOP" in x["tags"] for x in reviews
        ),
        "recent_incidents":issues[-max(1,min(int(limit),15)):],
        "important_limitation":"Price-derived stop classification is not OKX algorithm/fill history; do not assert causality",
    }

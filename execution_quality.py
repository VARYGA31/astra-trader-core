#!/usr/bin/env python3
"""
Deterministic entry-execution quality checks.

This module does not place orders. It:
- evaluates R:R at the actual tradable reference price,
- derives the worst acceptable FOK limit price,
- audits the actual average fill,
- measures adverse slippage.

All percentage values returned here are percentages, not fractions.
"""
import config

def rr(entry, stop, target):
    entry=float(entry); stop=float(stop); target=float(target)
    risk=abs(entry-stop)
    return abs(target-entry)/risk if risk>0 else 0.0

def min_rr_for_mode(mode, scalp_tier=None):
    mode=str(mode or "NORMAL").upper()
    if mode=="TRANSITION":
        return float(config.MTF_TRANSITION_MIN_TP1_R), float(config.MTF_TRANSITION_MIN_TP2_R)
    if mode=="SCALP":
        if str(scalp_tier or "PRIME").upper()=="FAST":
            return float(config.SCALP_FAST_MIN_TP1_R), float(config.SCALP_FAST_MIN_TP2_R)
        return float(config.SCALP_MIN_TP1_R), float(config.SCALP_MIN_TP2_R)
    if mode=="MICRO":
        return float(config.MICRO_MIN_TP1_R), float(config.MICRO_MIN_TP2_R)
    return float(config.MIN_TP1_R), float(config.MIN_TP2_R)

def max_slippage_pct(asset, mode="NORMAL"):
    asset=str(asset or "").upper()
    if str(mode or "NORMAL").upper()=="MICRO":
        return float(config.MICRO_MAX_ENTRY_SLIPPAGE_PCT)
    if asset=="XAU":
        return float(config.XAU_MAX_ENTRY_SLIPPAGE_PCT)
    if asset=="GRAM":
        return float(config.GRAM_MAX_ENTRY_SLIPPAGE_PCT)
    return float(config.CRYPTO_MAX_ENTRY_SLIPPAGE_PCT)

def audit_price(action, entry, stop, tp1, tp2, min_tp1_r, min_tp2_r):
    action=str(action).upper()
    try:
        entry=float(entry); stop=float(stop); tp1=float(tp1); tp2=float(tp2)
    except Exception:
        return {"passed":False,"reason":"INVALID_EXECUTION_PRICES"}

    if min(entry,stop,tp1,tp2)<=0:
        return {"passed":False,"reason":"INVALID_EXECUTION_PRICES"}

    if action=="LONG":
        levels_ok=stop < entry < tp1 < tp2
    elif action=="SHORT":
        levels_ok=stop > entry > tp1 > tp2
    else:
        return {"passed":False,"reason":"INVALID_ACTION"}

    if not levels_ok:
        return {
            "passed":False,
            "reason":"INVALID_LEVELS_AT_EXECUTION",
            "entry":entry,"stop_loss":stop,"take_profit_1":tp1,"take_profit_2":tp2,
        }

    r1=rr(entry,stop,tp1)
    r2=rr(entry,stop,tp2)
    passed=(r1+1e-12>=float(min_tp1_r) and r2+1e-12>=float(min_tp2_r))
    return {
        "passed":passed,
        "reason":"OK" if passed else "EXECUTION_RR_TOO_LOW",
        "entry":entry,
        "tp1_r":r1,
        "tp2_r":r2,
        "minimum_tp1_r":float(min_tp1_r),
        "minimum_tp2_r":float(min_tp2_r),
    }

def micro_net_edge(entry, stop, tp1, tp2, taker_fee_pct_per_side=None, slippage_pct_per_side=None):
    """Estimate MICRO profitability after round-trip taker fees + slippage.

    Percent inputs are percentage points (0.05 means 0.05%), matching the rest
    of this module. This is a conservative pre-trade estimate, not a promise.
    """
    entry=float(entry); stop=float(stop); tp1=float(tp1); tp2=float(tp2)
    risk_pct=(abs(entry-stop)/entry*100.0) if entry>0 else 0.0
    fee=float(
        config.MICRO_FALLBACK_TAKER_FEE_PCT_PER_SIDE
        if taker_fee_pct_per_side is None else taker_fee_pct_per_side
    )
    slip=float(
        config.MICRO_ESTIMATED_SLIPPAGE_PCT_PER_SIDE
        if slippage_pct_per_side is None else slippage_pct_per_side
    )
    cost_pct=2.0*(max(0.0,fee)+max(0.0,slip))
    if risk_pct<=0:
        return {"passed":False,"reason":"INVALID_MICRO_RISK_DISTANCE"}

    gross1=abs(tp1-entry)/entry*100.0
    gross2=abs(tp2-entry)/entry*100.0
    cost_r=cost_pct/risk_pct
    net1=(gross1-cost_pct)/risk_pct
    net2=(gross2-cost_pct)/risk_pct
    passed=(
        cost_r<=float(config.MICRO_MAX_ROUNDTRIP_COST_R)+1e-12
        and net1>=float(config.MICRO_MIN_NET_TP1_R)-1e-12
        and net2>=float(config.MICRO_MIN_NET_TP2_R)-1e-12
    )
    return {
        "passed":passed,
        "reason":"OK" if passed else "MICRO_NET_EDGE_TOO_LOW",
        "risk_distance_pct":risk_pct,
        "taker_fee_pct_per_side":fee,
        "estimated_slippage_pct_per_side":slip,
        "estimated_roundtrip_cost_pct":cost_pct,
        "cost_r":cost_r,
        "gross_tp1_r":gross1/risk_pct,
        "gross_tp2_r":gross2/risk_pct,
        "net_tp1_r":net1,
        "net_tp2_r":net2,
        "maximum_cost_r":float(config.MICRO_MAX_ROUNDTRIP_COST_R),
        "minimum_net_tp1_r":float(config.MICRO_MIN_NET_TP1_R),
        "minimum_net_tp2_r":float(config.MICRO_MIN_NET_TP2_R),
    }

def adverse_slippage_pct(action, reference, fill):
    action=str(action).upper()
    reference=float(reference); fill=float(fill)
    if reference<=0:
        return None
    if action=="LONG":
        return max(0.0,(fill-reference)/reference*100.0)
    if action=="SHORT":
        return max(0.0,(reference-fill)/reference*100.0)
    return None

def total_fill_delta_pct(reference, fill):
    reference=float(reference); fill=float(fill)
    return ((fill-reference)/reference*100.0) if reference>0 else None

def _rr_boundary(action, stop, target, minimum_r):
    """Worst entry still satisfying R >= minimum_r.

    Algebra is the same for LONG and SHORT:
        boundary = (target + R*stop) / (1+R)
    For LONG, fill must be <= boundary.
    For SHORT, fill must be >= boundary.
    """
    return (float(target)+float(minimum_r)*float(stop))/(1.0+float(minimum_r))

def raw_fok_limit(action, reference, stop, tp1, tp2, min_tp1_r, min_tp2_r, max_adverse_slippage_pct):
    """Return the worst acceptable fill/limit before tick rounding."""
    action=str(action).upper()
    reference=float(reference)
    slip=float(max_adverse_slippage_pct)/100.0

    b1=_rr_boundary(action,stop,tp1,min_tp1_r)
    b2=_rr_boundary(action,stop,tp2,min_tp2_r)

    if action=="LONG":
        slip_cap=reference*(1.0+slip)
        return min(slip_cap,b1,b2)
    if action=="SHORT":
        slip_floor=reference*(1.0-slip)
        return max(slip_floor,b1,b2)
    raise ValueError("INVALID_ACTION")

def build_entry_guard(asset, action, reference, stop, tp1, tp2, mode="NORMAL", scalp_tier=None):
    r1,r2=min_rr_for_mode(mode,scalp_tier)
    audit=audit_price(action,reference,stop,tp1,tp2,r1,r2)
    slip=max_slippage_pct(asset,mode)
    out={
        "asset":str(asset).upper(),
        "action":str(action).upper(),
        "mode":str(mode or "NORMAL").upper(),
        "scalp_tier":str(scalp_tier).upper() if scalp_tier else None,
        "reference_price":float(reference),
        "max_adverse_slippage_pct":slip,
        "minimum_tp1_r":r1,
        "minimum_tp2_r":r2,
        "pre_order_audit":audit,
    }
    if not audit.get("passed"):
        out["passed"]=False
        out["reason"]="PRE_ORDER_RR_TOO_LOW"
        return out

    raw=raw_fok_limit(action,reference,stop,tp1,tp2,r1,r2,slip)
    out.update({
        "passed":True,
        "reason":"OK",
        "raw_fok_limit_price":raw,
    })
    return out

def audit_fill(asset, action, reference, fill, stop, tp1, tp2, mode="NORMAL", scalp_tier=None):
    r1,r2=min_rr_for_mode(mode,scalp_tier)
    rr_audit=audit_price(action,fill,stop,tp1,tp2,r1,r2)
    adverse=adverse_slippage_pct(action,reference,fill)
    maximum=max_slippage_pct(asset,mode)
    slip_ok=(adverse is not None and adverse<=maximum+1e-12)
    return {
        "passed":bool(rr_audit.get("passed") and slip_ok),
        "reason":"OK" if rr_audit.get("passed") and slip_ok else (
            "POST_FILL_SLIPPAGE_TOO_HIGH" if rr_audit.get("passed") and not slip_ok
            else "POST_FILL_RR_TOO_LOW"
        ),
        "reference_price":float(reference),
        "actual_fill_price":float(fill),
        "adverse_slippage_pct":adverse,
        "fill_delta_pct":total_fill_delta_pct(reference,fill),
        "max_adverse_slippage_pct":maximum,
        "tp1_r":rr_audit.get("tp1_r"),
        "tp2_r":rr_audit.get("tp2_r"),
        "minimum_tp1_r":r1,
        "minimum_tp2_r":r2,
        "levels_reason":rr_audit.get("reason"),
    }

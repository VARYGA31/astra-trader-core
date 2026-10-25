"""Passive NORMAL stop-distance audit. No order/risk/model authority."""

ORDER_CAPABILITY = False
RISK_VETO_CAPABILITY = False


def examine(decision, minimum_pct=0.4, maximum_pct=8.0):
    """Return a hypothetical stop-distance classification, never a veto."""
    try:
        if str(decision.get("strategy_mode") or "NORMAL").upper() != "NORMAL":
            return None
        entry = float(decision.get("entry") or decision.get("entry_price") or 0)
        stop = float(decision.get("stop_loss") or 0)
        if entry <= 0 or stop <= 0:
            return {"status": "UNAVAILABLE", "order_capability": False}
        dist = abs(entry - stop) / entry * 100
        label = "BELOW_PROVISIONAL_MIN" if dist < minimum_pct else (
            "ABOVE_PROVISIONAL_MAX" if dist > maximum_pct else "WITHIN_PROVISIONAL_BAND"
        )
        return {
            "status": "SHADOW_ONLY", "asset": str(decision.get("asset") or ""),
            "stop_distance_pct": round(dist, 5), "classification": label,
            "provisional_min_pct": minimum_pct, "provisional_max_pct": maximum_pct,
            "order_capability": False, "risk_veto_capability": False,
        }
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNAVAILABLE", "order_capability": False}

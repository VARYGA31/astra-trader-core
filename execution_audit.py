#!/usr/bin/env python3
"""Passive post-close stop-execution diagnostics. No exchange/order authority."""


def stop_exit_audit(recent_closed):
    """Flag close prices worse than the recorded SL, without assuming why.

    A mark-triggered market stop is not a guaranteed fill price. This audit
    describes outcomes only; determining the cause requires OKX algo/fill history.
    """
    rows = []
    for trade in recent_closed or []:
        try:
            side = str(trade.get("side") or "").upper()
            entry = float(trade["entry"])
            stop = float(trade["stop_loss"])
            close = float(trade["exit_price"])
            if side not in {"LONG", "SHORT"} or min(entry, stop, close) <= 0:
                continue
            direction = 1 if side == "LONG" else -1
            risk = (entry - stop) * direction
            if risk <= 0:
                continue
            adverse = (stop - close) * direction
            if adverse <= 0:
                continue
            rows.append({
                "asset":trade.get("asset"),
                "timestamp_utc":trade.get("timestamp_utc"),
                "reason":trade.get("reason"),
                "planned_stop":stop,
                "exit_price":close,
                "adverse_beyond_stop_pct":round(adverse / stop * 100, 5),
                "adverse_beyond_stop_r":round(adverse / risk, 4),
                "pnl_usd":trade.get("pnl_usd"),
                "verification":"ORDER_AND_ALGO_HISTORY_REQUIRED",
            })
        except (TypeError, ValueError, KeyError, ZeroDivisionError):
            continue
    return {"status":"OK", "closed_sample":len(recent_closed or []),
            "beyond_stop_count":len(rows), "beyond_stop":rows[-5:],
            "order_capability":False, "model_capability":False}

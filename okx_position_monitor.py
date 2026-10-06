#!/usr/bin/env python3
import json
from pathlib import Path
from datetime import datetime, timezone

import config
from okx_demo_adapter import OKXDemoAdapter
import telegram_notifier
import trade_journal
import cooldown
import demo_ledger

STATE = Path(config.STATE_DIR) / "okx_active_trades.json"

def load():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save(data):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE)

def register_trade(record):
    d = load()
    d[record["asset"]] = record
    save(d)

def remove_trade(asset):
    d = load()
    d.pop(asset, None)
    save(d)

def active_summary():
    d = load()
    exposure = sum(float(x.get("remaining_notional_usd", x.get("notional_usd", 0))) for x in d.values())
    return {
        "open_positions": len(d),
        "current_exposure_usd": exposure,
        "assets": list(d.keys()),
    }

def check_once():
    if config.EXECUTION_MODE != "okx_demo":
        return {"status":"SKIPPED","reason":"NOT_OKX_DEMO"}

    adapter = OKXDemoAdapter()
    state = load()
    results = []

    for asset, rec in list(state.items()):
        pos = adapter.get_position(asset)

        if not pos:
            hist = adapter.latest_position_history(asset) or {}
            pnl = float(hist.get("realizedPnl") or 0)
            exit_px = float(hist.get("closeAvgPx") or 0) if hist.get("closeAvgPx") else None
            reason = "EXCHANGE_CLOSE"
            stop = rec.get("stop_loss")
            if exit_px and stop:
                tolerance = max(abs(float(stop))*0.002, 1e-12)
                if abs(exit_px - float(stop)) <= tolerance:
                    reason = "STOP_LOSS"

            message = {
                **rec,
                "exit_price": exit_px,
                "pnl_usd": pnl,
                "reason": reason,
                "mode": "OKX DEMO",
            }
            telegram_notifier.notify_close(message)
            trade_journal.append_event({"event":"OKX_POSITION_CLOSED", **message})
            demo_ledger.apply_closed_trade(pnl)
            cooldown.set_cooldown(asset, reason=reason)
            remove_trade(asset)
            results.append({"asset":asset,"status":"CLOSED","reason":reason,"pnl_usd":pnl})
            continue

        mark = float(pos.get("markPx") or pos.get("last") or pos.get("avgPx") or 0)
        qty = abs(float(pos.get("pos") or 0))
        side = rec["side"]
        tp1 = rec.get("take_profit_1")
        tp2 = rec.get("take_profit_2")

        hit_tp1 = (
            tp1 is not None and not rec.get("tp1_taken")
            and ((side=="LONG" and mark >= float(tp1)) or (side=="SHORT" and mark <= float(tp1)))
        )
        hit_tp2 = (
            tp2 is not None
            and ((side=="LONG" and mark >= float(tp2)) or (side=="SHORT" and mark <= float(tp2)))
        )

        if hit_tp2:
            adapter.close_market(asset, side, qty)
            results.append({"asset":asset,"status":"TP2_CLOSE_SUBMITTED","qty_contracts":qty})
        elif hit_tp1:
            try:
                half = float(adapter.normalize_qty(asset, qty/2))
            except Exception:
                half = 0.0
            if half > 0 and half < qty:
                adapter.close_market(asset, side, half)
                rec["tp1_taken"] = True
                ratio = max(0.0, min(1.0, (qty-half)/qty))
                rec["remaining_notional_usd"] = float(rec.get("remaining_notional_usd",rec.get("notional_usd",0))) * ratio
                state[asset] = rec
                save(state)
                telegram_notifier.notify_partial({
                    **rec,
                    "exit_price":mark,
                    "closed_qty":half,
                    "remaining_qty":qty-half,
                    "reason":"TAKE_PROFIT_1",
                })
                trade_journal.append_event({
                    "event":"OKX_TP1",
                    "asset":asset,
                    "price":mark,
                    "closed_qty_contracts":half,
                })
                results.append({"asset":asset,"status":"TP1_CLOSE_SUBMITTED","qty_contracts":half})
            else:
                results.append({"asset":asset,"status":"HELD","reason":"TP1_PARTIAL_BELOW_MIN","mark_price":mark})
        else:
            results.append({"asset":asset,"status":"HELD","mark_price":mark,"qty_contracts":qty})

    return {"status":"OK","results":results,"ledger":demo_ledger.status()}

if __name__ == "__main__":
    print(json.dumps(check_once(), ensure_ascii=False))

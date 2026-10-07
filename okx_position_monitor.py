#!/usr/bin/env python3
import json
from pathlib import Path
from datetime import datetime

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
    asset = record["asset"]
    if asset in d:
        raise RuntimeError(f"LOCAL_STATE_ALREADY_HAS_OPEN_POSITION:{asset}")
    d[asset] = record
    save(d)

def remove_trade(asset):
    d = load()
    d.pop(asset, None)
    save(d)

def active_summary():
    """Use OKX as source of truth, not the local JSON ledger."""
    if config.EXECUTION_MODE != "okx_demo":
        return {"open_positions":0,"current_exposure_usd":0.0,"assets":[],"details":[]}
    return OKXDemoAdapter().exchange_active_summary()

def _classify_close(exit_px, rec):
    if not exit_px:
        return "EXCHANGE_CLOSE"
    levels = [
        ("STOP_LOSS", rec.get("stop_loss")),
        ("TAKE_PROFIT_1", rec.get("take_profit_1")),
        ("TAKE_PROFIT_2", rec.get("take_profit_2")),
    ]
    best = ("EXCHANGE_CLOSE", None)
    for name, px in levels:
        if px is None:
            continue
        dist = abs(exit_px - float(px))
        if best[1] is None or dist < best[1]:
            best = (name, dist)
    tolerance = max(abs(exit_px) * 0.004, 1e-12)
    return best[0] if best[1] is not None and best[1] <= tolerance else "EXCHANGE_CLOSE"

def check_once():
    if config.EXECUTION_MODE != "okx_demo":
        return {"status":"SKIPPED","reason":"NOT_OKX_DEMO"}

    adapter = OKXDemoAdapter()
    state = load()
    results = []

    # OKX is authoritative. This also exposes any unexpected/untracked positions.
    exchange = adapter.exchange_active_summary()
    tracked_assets = set(state.keys())
    untracked = [x for x in exchange["assets"] if x not in tracked_assets]
    for asset in untracked:
        results.append({"asset":asset,"status":"UNTRACKED_EXCHANGE_POSITION"})

    for asset, rec in list(state.items()):
        pos = adapter.get_position(asset)

        if not pos:
            opened_at = rec.get("opened_at_utc")
            opened_ms = None
            if opened_at:
                try:
                    opened_ms = int(datetime.fromisoformat(opened_at.replace("Z","+00:00")).timestamp() * 1000)
                except Exception:
                    opened_ms = None

            hist = adapter.wait_position_history(asset, opened_at_ms=opened_ms, timeout=10) or {}
            pnl = float(hist.get("realizedPnl") or 0)
            exit_px = float(hist.get("closeAvgPx") or 0) if hist.get("closeAvgPx") else None
            reason = _classify_close(exit_px, rec)

            message = {
                **rec,
                "exit_price":exit_px,
                "pnl_usd":pnl,
                "reason":reason,
                "mode":"OKX DEMO",
            }
            telegram_notifier.notify_close(message)
            trade_journal.append_event({"event":"OKX_POSITION_CLOSED", **message})
            demo_ledger.apply_closed_trade(pnl)
            cooldown.set_cooldown(asset, reason=reason)
            remove_trade(asset)
            results.append({"asset":asset,"status":"CLOSED","reason":reason,"pnl_usd":pnl})
            continue

        qty = abs(float(pos.get("pos") or 0))
        last_qty = float(rec.get("last_qty_contracts", rec.get("qty_contracts", qty)))

        # Detect exchange-side TP1 reduction. Do NOT submit another close order here.
        if qty + 1e-12 < last_qty:
            closed_qty = last_qty - qty
            rec["tp1_taken"] = True
            rec["last_qty_contracts"] = qty
            if last_qty > 0:
                ratio = qty / last_qty
                rec["remaining_notional_usd"] = float(
                    rec.get("remaining_notional_usd", rec.get("notional_usd",0))
                ) * ratio
            state[asset] = rec
            save(state)

            mark = float(pos.get("markPx") or pos.get("avgPx") or 0)
            telegram_notifier.notify_partial({
                **rec,
                "exit_price":mark,
                "closed_qty":closed_qty,
                "remaining_qty":qty,
                "reason":"EXCHANGE_SIDE_TP1_OR_PARTIAL_REDUCTION",
            })
            trade_journal.append_event({
                "event":"OKX_PARTIAL_REDUCTION",
                "asset":asset,
                "price":mark,
                "closed_qty_contracts":closed_qty,
                "remaining_qty_contracts":qty,
            })
            results.append({
                "asset":asset,
                "status":"PARTIAL_REDUCTION_DETECTED",
                "closed_qty_contracts":closed_qty,
                "remaining_qty_contracts":qty,
            })
        else:
            rec["last_qty_contracts"] = qty
            state[asset] = rec
            save(state)
            results.append({
                "asset":asset,
                "status":"HELD",
                "mark_price":float(pos.get("markPx") or pos.get("avgPx") or 0),
                "qty_contracts":qty,
                "protection_mode":rec.get("protection_mode"),
            })

    return {
        "status":"OK",
        "results":results,
        "exchange_summary":exchange,
        "ledger":demo_ledger.status(),
    }

if __name__=="__main__":
    print(json.dumps(check_once(), ensure_ascii=False))

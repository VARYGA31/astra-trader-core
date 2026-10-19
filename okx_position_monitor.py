#!/usr/bin/env python3
import json
import time
from pathlib import Path
from datetime import datetime, timezone

import config
from okx_demo_adapter import OKXDemoAdapter
import telegram_notifier
import trade_journal
import cooldown
import demo_ledger

STATE = Path(config.STATE_DIR) / "okx_active_trades.json"
PROCESSED = Path(config.STATE_DIR) / "okx_processed_closes.json"

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def _micro_time_stop_due(rec, now_ts=None):
    if str((rec or {}).get("strategy_mode") or "").upper()!="MICRO":
        return False
    opened=(rec or {}).get("opened_at_utc")
    if not opened:
        return False
    try:
        opened_ts=datetime.fromisoformat(str(opened).replace("Z","+00:00")).timestamp()
    except Exception:
        return False
    current=time.time() if now_ts is None else float(now_ts)
    return current-opened_ts>=float(config.MICRO_MAX_HOLD_SECONDS)

def _atomic_save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

def load():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save(data):
    _atomic_save(STATE, data)

def _load_processed():
    try:
        return json.loads(PROCESSED.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_processed(data):
    # Keep file bounded.
    if len(data) > 1000:
        items = list(data.items())[-1000:]
        data = dict(items)
    _atomic_save(PROCESSED, data)

def _close_key(asset, rec):
    return f"{asset}:{rec.get('order_id') or rec.get('opened_at_utc') or 'unknown'}"

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
    forced = rec.get("forced_close_reason")
    if forced:
        return str(forced)
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

def _confirm_position_absent(adapter, asset, checks=3, delay=0.8):
    """Avoid treating a transient empty OKX response as a real close."""
    for i in range(checks):
        if adapter.get_position(asset):
            return False
        if i + 1 < checks:
            time.sleep(delay)
    return True

def _claim_close_once(asset, rec):
    """At-most-once claim for close notification + ledger accounting."""
    key = _close_key(asset, rec)
    processed = _load_processed()
    if key in processed:
        return False, key

    # Claim BEFORE Telegram/accounting. If the process crashes afterwards,
    # we prefer one missing notification over duplicated PnL/accounting spam.
    processed[key] = {
        "asset": asset,
        "order_id": rec.get("order_id"),
        "claimed_at_utc": now_iso(),
        "status": "CLAIMED",
    }
    _save_processed(processed)

    # Remove stale active record BEFORE external side effects.
    # This is the main protection against a 10-second notification loop.
    remove_trade(asset)
    return True, key

def _complete_close_claim(key, message):
    processed = _load_processed()
    row = processed.get(key, {})
    row.update({
        "status": "PROCESSED",
        "processed_at_utc": now_iso(),
        "exit_price": message.get("exit_price"),
        "pnl_usd": message.get("pnl_usd"),
        "reason": message.get("reason"),
    })
    processed[key] = row
    _save_processed(processed)

def mark_forced_close(asset, reason, details=None):
    d = load()
    rec = d.get(asset)
    if not rec:
        return {"status":"NOT_TRACKED","asset":asset}
    rec["forced_close_reason"] = reason
    rec["forced_close_details"] = details or {}
    rec["forced_close_marked_at_utc"] = now_iso()
    d[asset] = rec
    save(d)
    return {"status":"OK","asset":asset,"reason":reason}

def check_once():
    if config.EXECUTION_MODE != "okx_demo":
        return {"status":"SKIPPED","reason":"NOT_OKX_DEMO"}

    adapter = OKXDemoAdapter()
    state = load()
    results = []

    exchange = adapter.exchange_active_summary()
    tracked_assets = set(state.keys())
    untracked = [x for x in exchange["assets"] if x not in tracked_assets]
    for asset in untracked:
        results.append({"asset":asset,"status":"UNTRACKED_EXCHANGE_POSITION"})

    for asset, rec in list(state.items()):
        pos = adapter.get_position(asset)

        if not pos:
            if not _confirm_position_absent(adapter, asset):
                results.append({"asset":asset,"status":"TRANSIENT_EMPTY_POSITION_IGNORED"})
                continue

            claimed, close_key = _claim_close_once(asset, rec)
            if not claimed:
                # Ensure stale local state cannot keep producing work.
                remove_trade(asset)
                results.append({"asset":asset,"status":"DUPLICATE_CLOSE_SUPPRESSED"})
                continue

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
                "close_event_id":close_key,
            }

            # Each of these must happen only after the persistent claim above.
            telegram_notifier.notify_close(message)
            trade_journal.append_event({"event":"OKX_POSITION_CLOSED", **message})
            demo_ledger.apply_closed_trade(pnl)
            rec_mode=str(rec.get("strategy_mode") or "NORMAL").upper()
            if rec_mode=="MICRO":
                micro_cd=config.MICRO_STOP_LOSS_COOLDOWN_SECONDS if reason=="STOP_LOSS" else config.MICRO_COOLDOWN_SECONDS
                cooldown.set_cooldown(asset, seconds=micro_cd, reason=reason)
            elif reason == "STOP_LOSS":
                stop_cd=(config.SCALP_STOP_LOSS_COOLDOWN_SECONDS if rec_mode=="SCALP" else config.STOP_LOSS_COOLDOWN_SECONDS)
                cooldown.set_cooldown(asset, seconds=stop_cd, reason=reason)
            elif str(reason).startswith("EMERGENCY_"):
                cooldown.set_cooldown(asset, seconds=config.EMERGENCY_EXIT_COOLDOWN_SECONDS, reason=reason)
            else:
                cooldown.set_cooldown(asset, reason=reason)
            _complete_close_claim(close_key, message)

            results.append({
                "asset":asset,
                "status":"CLOSED",
                "reason":reason,
                "pnl_usd":pnl,
                "close_event_id":close_key,
            })
            continue

        qty = abs(float(pos.get("pos") or 0))

        # MICRO is a 1-5 minute experiment. It never turns into an accidental
        # swing position: after the hard hold limit, close the remaining size.
        if qty>0 and _micro_time_stop_due(rec):
            try:
                cleanup=adapter.cancel_attached_algos(asset,rec.get("order_id"))
                close=adapter.close_market(asset,str(rec.get("side") or "").upper(),qty)
                row=(close.get("data") or [{}])[0]
                close_ord=row.get("ordId")
                if not close_ord:
                    raise RuntimeError(f"MICRO_TIME_STOP_CLOSE_NO_ORDER_ID:{close}")
                terminal=adapter.wait_filled(asset,close_ord,timeout=15) or {}
                if terminal.get("state")!="filled":
                    raise RuntimeError(f"MICRO_TIME_STOP_CLOSE_NOT_FILLED:{terminal}")
                rec["forced_close_reason"]="MICRO_TIME_STOP"
                rec["forced_close_details"]={
                    "max_hold_seconds":config.MICRO_MAX_HOLD_SECONDS,
                    "close_order_id":close_ord,
                    "algo_cleanup":cleanup,
                }
                rec["forced_close_marked_at_utc"]=now_iso()
                state=load(); state[asset]=rec; save(state)
                trade_journal.append_event({
                    "event":"MICRO_TIME_STOP_SUBMITTED",
                    "asset":asset,
                    "side":rec.get("side"),
                    "qty_contracts":qty,
                    "close_order_id":close_ord,
                    "max_hold_seconds":config.MICRO_MAX_HOLD_SECONDS,
                    "timestamp_utc":now_iso(),
                })
                results.append({"asset":asset,"status":"MICRO_TIME_STOP_FILLED","close_order_id":close_ord})
                continue
            except Exception as e:
                results.append({"asset":asset,"status":"MICRO_TIME_STOP_FAILED","error":str(e)})
                continue

        last_qty = float(rec.get("last_qty_contracts", rec.get("qty_contracts", qty)))

        # Detect exchange-side partial reduction only. Do not submit a close here.
        if qty + 1e-12 < last_qty:
            closed_qty = last_qty - qty
            rec["tp1_taken"] = True
            rec["last_qty_contracts"] = qty
            if last_qty > 0:
                ratio = qty / last_qty
                rec["remaining_notional_usd"] = float(
                    rec.get("remaining_notional_usd", rec.get("notional_usd",0))
                ) * ratio
            state = load()
            state[asset] = rec
            save(state)

            mark = float(pos.get("markPx") or pos.get("avgPx") or 0)
            partial_id = f"{asset}:{rec.get('order_id')}:{qty}"
            telegram_notifier.notify_partial({
                **rec,
                "exit_price":mark,
                "closed_qty":closed_qty,
                "remaining_qty":qty,
                "reason":"EXCHANGE_SIDE_PARTIAL_REDUCTION",
                "partial_event_id":partial_id,
            })
            trade_journal.append_event({
                "event":"OKX_PARTIAL_REDUCTION",
                "asset":asset,
                "price":mark,
                "closed_qty_contracts":closed_qty,
                "remaining_qty_contracts":qty,
                "partial_event_id":partial_id,
            })
            results.append({
                "asset":asset,
                "status":"PARTIAL_REDUCTION_DETECTED",
                "closed_qty_contracts":closed_qty,
                "remaining_qty_contracts":qty,
            })
        else:
            rec["last_qty_contracts"] = qty
            state = load()
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

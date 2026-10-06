#!/usr/bin/env python3
import json
from pathlib import Path
from datetime import datetime, timezone

import config
from bybit_testnet_adapter import BybitTestnetAdapter
import telegram_notifier
import trade_journal
import cooldown

STATE = Path(config.STATE_DIR) / "bybit_active_trades.json"

def _load():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save(data):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp=STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    tmp.replace(STATE)

def register_trade(record):
    d=_load()
    d[record["asset"]]=record
    _save(d)

def remove_trade(asset):
    d=_load(); d.pop(asset,None); _save(d)

def active_count():
    return len(_load())

def check_once():
    if config.EXECUTION_MODE != "bybit_testnet":
        return {"status":"SKIPPED","reason":"NOT_BYBIT_TESTNET"}
    adapter=BybitTestnetAdapter()
    state=_load()
    results=[]

    for asset, rec in list(state.items()):
        pos=adapter.get_position(asset)
        if not pos:
            cp=adapter.latest_closed_pnl(asset) or {}
            exit_price=float(cp.get("avgExitPrice") or 0) if cp else None
            pnl=float(cp.get("closedPnl") or 0) if cp else None
            reason="EXCHANGE_CLOSE"
            stop=rec.get("stop_loss")
            if exit_price and stop:
                tol=max(abs(float(stop))*0.002, 1e-12)
                if abs(exit_price-float(stop)) <= tol:
                    reason="STOP_LOSS"
            msg={
                **rec,
                "exit_price":exit_price,
                "pnl_usd":pnl,
                "reason":reason,
                "mode":"BYBIT TESTNET",
            }
            telegram_notifier.notify_close(msg)
            trade_journal.append_event({"event":"BYBIT_POSITION_CLOSED",**msg})
            cooldown.set_cooldown(asset,reason=reason)
            remove_trade(asset)
            results.append({"asset":asset,"status":"CLOSED","reason":reason,"pnl_usd":pnl})
            continue

        current=float(pos.get("markPrice") or pos.get("avgPrice") or 0)
        qty=float(pos.get("size") or 0)
        side=rec["side"]
        tp1=rec.get("take_profit_1"); tp2=rec.get("take_profit_2")
        hit_tp1 = tp1 is not None and not rec.get("tp1_taken") and ((side=="LONG" and current>=float(tp1)) or (side=="SHORT" and current<=float(tp1)))
        hit_tp2 = tp2 is not None and ((side=="LONG" and current>=float(tp2)) or (side=="SHORT" and current<=float(tp2)))

        if hit_tp2:
            adapter.close_market(asset,side,qty)
            results.append({"asset":asset,"status":"TP2_CLOSE_SUBMITTED","qty":qty})
        elif hit_tp1:
            close_qty=qty/2
            adapter.close_market(asset,side,close_qty)
            rec["tp1_taken"]=True
            state[asset]=rec; _save(state)
            telegram_notifier.notify_partial({
                **rec,"exit_price":current,"closed_qty":close_qty,"remaining_qty":qty-close_qty,"reason":"TAKE_PROFIT_1"
            })
            trade_journal.append_event({"event":"BYBIT_TP1","asset":asset,"price":current,"closed_qty":close_qty})
            results.append({"asset":asset,"status":"TP1_CLOSE_SUBMITTED","qty":close_qty})
        else:
            results.append({"asset":asset,"status":"HELD","mark_price":current,"qty":qty})
    return {"status":"OK","results":results}

if __name__=="__main__":
    print(json.dumps(check_once(),ensure_ascii=False))

#!/usr/bin/env python3
from datetime import datetime, timezone

import config
import telegram_notifier
from okx_demo_adapter import OKXDemoAdapter
import okx_position_monitor

def open_trade(decision, risk):
    if config.EXECUTION_MODE == "paper":
        return {"status":"ROUTER_PAPER","note":"paper execution handled by trade_cycle"}

    if config.EXECUTION_MODE != "okx_demo":
        return {"status":"REJECTED","reason":"UNKNOWN_EXECUTION_MODE"}

    adapter = OKXDemoAdapter()
    opened = adapter.open_market(
        decision["asset"],
        decision["action"],
        risk["position_notional_usd"],
        risk["leverage"],
        risk["stop_loss"],
    )

    entry = opened["entry"]
    notional = opened["position_value_usd_approx"]
    record = {
        "asset": decision["asset"],
        "inst_id": opened["inst_id"],
        "side": decision["action"],
        "timeframe": decision.get("timeframe") or config.TRADING_TIMEFRAME,
        "entry": entry,
        "qty_contracts": opened["qty_contracts"],
        "notional_usd": notional,
        "remaining_notional_usd": notional,
        "margin_usd": notional/opened["leverage"] if opened["leverage"] else None,
        "leverage": opened["leverage"],
        "stop_loss": risk["stop_loss"],
        "take_profit_1": decision.get("take_profit_1"),
        "take_profit_2": decision.get("take_profit_2"),
        "order_id": opened["order_id"],
        "opened_at_utc": datetime.now(timezone.utc).isoformat(),
        "tp1_taken": False,
        "mode":"OKX DEMO",
    }
    okx_position_monitor.register_trade(record)
    telegram_notifier.notify_open(record)
    return {"status":"OKX_DEMO_OPENED","trade":record}

def sync_positions():
    if config.EXECUTION_MODE == "okx_demo":
        return okx_position_monitor.check_once()
    return {"status":"SKIPPED","reason":"PAPER_MODE"}

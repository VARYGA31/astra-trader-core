#!/usr/bin/env python3
"""
Controlled OKX Demo round-trip connectivity test.

This is NOT a strategy signal.
It opens one small BTC demo position through the real execution adapter,
sends the normal Telegram OPEN message, waits briefly, then closes it
with reduce-only and sends the CLOSE message.

It refuses to run unless EXECUTION_MODE=okx_demo and AUTO_DECISION=false.
"""
import json
import sys
import time
from datetime import datetime, timezone

import config
import demo_ledger
import risk_engine
import telegram_notifier
import trade_journal
from okx_demo_adapter import OKXDemoAdapter

asset = (sys.argv[1] if len(sys.argv) > 1 else "BTC").upper()
side = (sys.argv[2] if len(sys.argv) > 2 else "LONG").upper()

result = {
    "status": "STARTED",
    "asset": asset,
    "side": side,
    "execution_mode": config.EXECUTION_MODE,
}

if config.EXECUTION_MODE != "okx_demo":
    result.update({"status":"REFUSED","reason":"EXECUTION_MODE_MUST_BE_okx_demo"})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(2)

if config.AUTO_DECISION:
    result.update({"status":"REFUSED","reason":"AUTO_DECISION_MUST_BE_false_FOR_ROUNDTRIP_TEST"})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(2)

if asset not in config.ALLOWED_ASSETS or side not in {"LONG","SHORT"}:
    result.update({"status":"REFUSED","reason":"INVALID_ASSET_OR_SIDE"})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(2)

adapter = OKXDemoAdapter()

existing = adapter.get_position(asset)
if existing:
    result.update({
        "status":"REFUSED",
        "reason":"EXISTING_POSITION_PRESENT",
        "existing_position": existing,
    })
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(2)

market_price = adapter.ticker(asset)
stop_loss = market_price * (0.98 if side == "LONG" else 1.02)
tp1 = market_price * (1.02 if side == "LONG" else 0.98)
tp2 = market_price * (1.04 if side == "LONG" else 0.96)

ledger = demo_ledger.status()
risk_input = {
    "asset": asset,
    "action": side,
    "equity": ledger["equity"],
    "initial_equity": ledger["initial_equity"],
    "daily_pnl": ledger["daily_pnl"],
    "open_positions": 0,
    "current_exposure_usd": 0,
    "entry": market_price,
    "stop_loss": stop_loss,
    "confidence": 80,
    "data_quality": "OK",
    "critical_news_verified": True,
    "volatility_regime": "NORMAL",
    "leverage": 3,
}

risk = risk_engine.evaluate(risk_input)
result["risk"] = risk

if risk.get("status") != "APPROVED":
    result.update({"status":"REFUSED","reason":"RISK_ENGINE_REJECTED"})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(2)

opened = adapter.open_market(
    asset=asset,
    action=side,
    notional_usd=risk["position_notional_usd"],
    leverage=risk["leverage"],
    stop_loss=risk["stop_loss"],
)

record = {
    "asset": asset,
    "inst_id": opened["inst_id"],
    "side": side,
    "timeframe": config.TRADING_TIMEFRAME,
    "entry": opened["entry"],
    "qty_contracts": opened["qty_contracts"],
    "notional_usd": opened["position_value_usd_approx"],
    "margin_usd": opened["position_value_usd_approx"] / opened["leverage"],
    "leverage": opened["leverage"],
    "stop_loss": risk["stop_loss"],
    "take_profit_1": tp1,
    "take_profit_2": tp2,
    "order_id": opened["order_id"],
    "opened_at_utc": datetime.now(timezone.utc).isoformat(),
    "mode": "OKX DEMO CONNECTIVITY TEST",
}

telegram_notifier.notify_open(record)
trade_journal.append_event({"event":"OKX_ROUNDTRIP_OPEN", **record})
result["open"] = record

time.sleep(8)

pos = adapter.get_position(asset)
if not pos:
    hist = adapter.latest_position_history(asset) or {}
    pnl = float(hist.get("realizedPnl") or 0)
    exit_price = float(hist.get("closeAvgPx") or 0) if hist.get("closeAvgPx") else None
    close_reason = "STOP_LOSS_OR_EXCHANGE_CLOSE_BEFORE_MANUAL_CLOSE"
else:
    qty = abs(float(pos.get("pos") or 0))
    close_submit = adapter.close_market(asset, side, qty)
    result["close_submit"] = close_submit

    deadline = time.time() + 15
    while time.time() < deadline and adapter.get_position(asset):
        time.sleep(0.8)

    hist = adapter.latest_position_history(asset) or {}
    pnl = float(hist.get("realizedPnl") or 0)
    exit_price = float(hist.get("closeAvgPx") or 0) if hist.get("closeAvgPx") else None
    close_reason = "MANUAL_ROUNDTRIP_TEST"

close_record = {
    **record,
    "exit_price": exit_price,
    "pnl_usd": pnl,
    "reason": close_reason,
    "mode": "OKX DEMO CONNECTIVITY TEST",
}
telegram_notifier.notify_close(close_record)
trade_journal.append_event({"event":"OKX_ROUNDTRIP_CLOSE", **close_record})
demo_ledger.apply_closed_trade(pnl)

result.update({
    "status":"OK",
    "close": close_record,
    "ledger_after": demo_ledger.status(),
})
print(json.dumps(result, ensure_ascii=False, indent=2))

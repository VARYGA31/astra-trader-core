#!/usr/bin/env python3
"""
ONE controlled OKX Demo protection test.

- Refuses to run unless EXECUTION_MODE=okx_demo
- Refuses to run unless AUTO_DECISION=false
- Refuses to run if the selected asset already has an open position
- Uses the real deterministic Risk Engine
- Opens exactly ONE Demo position
- Leaves it open so TP/SL can be inspected directly in OKX
- The position remains protected by exchange-side TP/SL
"""

import json
import sys

import config
import risk_engine
import execution_router
from okx_demo_adapter import OKXDemoAdapter

asset = (sys.argv[1] if len(sys.argv) > 1 else "ETH").upper()
side = (sys.argv[2] if len(sys.argv) > 2 else "LONG").upper()

result = {
    "status": "STARTED",
    "asset": asset,
    "side": side,
    "execution_mode": config.EXECUTION_MODE,
    "will_open_one_demo_order": True,
}

if config.EXECUTION_MODE != "okx_demo":
    result.update({"status":"REFUSED","reason":"EXECUTION_MODE_MUST_BE_okx_demo"})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(2)

if config.AUTO_DECISION:
    result.update({"status":"REFUSED","reason":"AUTO_DECISION_MUST_BE_false"})
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
        "reason":"ASSET_ALREADY_HAS_OPEN_POSITION",
        "existing_position": existing,
    })
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(2)

exchange = adapter.exchange_active_summary()
price = adapter.ticker(asset)

# 1R = 1% of price.
# TP1 = 1.2R, TP2 = 2.0R, satisfying the new hard minimums:
# MIN_TP1_R=1.0 and MIN_TP2_R=1.8
if side == "LONG":
    stop = price * 0.99
    tp1 = price * 1.012
    tp2 = price * 1.020
else:
    stop = price * 1.01
    tp1 = price * 0.988
    tp2 = price * 0.980

decision = {
    "asset": asset,
    "action": side,
    "entry": price,
    "stop_loss": stop,
    "take_profit_1": tp1,
    "take_profit_2": tp2,
    "confidence": 80,
    "data_quality": "OK",
    "volatility_regime": "NORMAL",
    "leverage": 3,
    "timeframe": config.TRADING_TIMEFRAME,
    "reason": "CONTROLLED_EXCHANGE_TP_SL_TEST",
}

risk_input = {
    **decision,
    "equity": config.INITIAL_EQUITY,
    "initial_equity": config.INITIAL_EQUITY,
    "daily_pnl": 0.0,
    "open_positions": exchange["open_positions"],
    "current_exposure_usd": exchange["current_exposure_usd"],
    "asset_already_open": asset in exchange.get("assets", []),
    "critical_news_verified": True,
}

risk = risk_engine.evaluate(risk_input)
result["planned_levels"] = {
    "entry_reference": price,
    "stop_loss": stop,
    "take_profit_1": tp1,
    "take_profit_2": tp2,
}
result["risk"] = risk

if risk.get("status") != "APPROVED":
    result.update({"status":"REFUSED","reason":"RISK_ENGINE_REJECTED"})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(2)

opened = execution_router.open_trade(decision, risk)
result["execution"] = opened

if opened.get("status") != "OKX_DEMO_OPENED":
    result.update({"status":"FAILED","reason":"ORDER_NOT_OPENED"})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(1)

result["status"] = "OK"
result["IMPORTANT"] = (
    "Do not enable AUTO_DECISION yet. Open OKX Demo and inspect the new position "
    "and its TP/SL orders. Send screenshots before continuing."
)
print(json.dumps(result, ensure_ascii=False, indent=2))

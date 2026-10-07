#!/usr/bin/env python3
import sys, json
from pathlib import Path
from datetime import datetime, timezone

import config, cooldown, decision_context, paper_execution, risk_engine
import execution_router
import demo_ledger
import okx_position_monitor

def parse_ts(x):
    try:
        return datetime.fromisoformat((x or "").replace("Z","+00:00"))
    except Exception:
        return None

def account_state():
    if config.EXECUTION_MODE == "okx_demo":
        ledger = demo_ledger.status()
        active = okx_position_monitor.active_summary()
        return {
            "initial_equity":ledger["initial_equity"],
            "equity":ledger["equity"],
            "daily_pnl":ledger["daily_pnl"],
            "open_positions":active["open_positions"],
            "current_exposure_usd":active["current_exposure_usd"],
            "open_assets":active.get("assets",[]),
            "exchange_positions":active.get("details",[]),
            "trading_halted":ledger["trading_halted"],
        }

    s = paper_execution.status()
    return {
        "initial_equity":s.get("initial_equity"),
        "equity":s.get("account_equity"),
        "daily_pnl":s.get("daily_realized_pnl",0),
        "open_positions":s.get("open_positions_count",0),
        "current_exposure_usd":s.get("current_exposure_usd",0),
        "open_assets":[],
        "trading_halted":s.get("trading_halted",False),
    }

def prepare(asset,hours=12):
    c = decision_context.build(asset,hours)
    s = account_state()
    ts = parse_ts(c.get("market",{}).get("generated_at_utc"))
    age = (datetime.now(timezone.utc)-ts).total_seconds() if ts else 10**9
    guards = {
        **c.get("guards",{}),
        "market_stale":age > config.STALE_MARKET_SECONDS,
        "cooldown":cooldown.status(asset),
        "trading_halted":s.get("trading_halted",False),
        "asset_already_open":asset in set(s.get("open_assets",[])),
    }
    return {
        "status":"READY_FOR_ASTRA" if c.get("status")=="OK" else "FAILED",
        "asset":asset,
        "decision_context":c,
        "execution_mode":config.EXECUTION_MODE,
        "timeframe":config.TRADING_TIMEFRAME,
        "account_state":s,
        "guards":guards,
    }

def execute(decision):
    asset = str(decision.get("asset","")).upper()
    action = str(decision.get("action","")).upper()
    if action == "WAIT":
        return {"status":"NO_TRADE","reason":"ASTRA_WAIT"}

    decision["timeframe"] = decision.get("timeframe") or config.TRADING_TIMEFRAME
    p = prepare(asset,12)
    g = p["guards"]

    if g.get("market_stale") or not g.get("market_ok"):
        return {"status":"REJECTED","reason":"MARKET_DATA_GUARD"}
    if not g.get("news_ok"):
        return {"status":"REJECTED","reason":"NEWS_DATA_GUARD"}
    if not g.get("critical_news_verified"):
        return {"status":"REJECTED","reason":"UNVERIFIED_HIGH_IMPACT_NEWS"}
    if g.get("cooldown",{}).get("active"):
        return {"status":"REJECTED","reason":"COOLDOWN_ACTIVE"}
    if g.get("trading_halted"):
        return {"status":"REJECTED","reason":"TRADING_HALTED"}
    if config.ONE_POSITION_PER_ASSET and g.get("asset_already_open"):
        return {"status":"REJECTED","reason":"ASSET_ALREADY_HAS_OPEN_POSITION"}

    s = p["account_state"]
    rinput = {
        **decision,
        "equity":s["equity"],
        "initial_equity":s["initial_equity"],
        "daily_pnl":s["daily_pnl"],
        "open_positions":s["open_positions"],
        "current_exposure_usd":s["current_exposure_usd"],
        "asset_already_open":g.get("asset_already_open",False),
        "critical_news_verified":True,
    }
    r = risk_engine.evaluate(rinput)
    if r.get("status") != "APPROVED":
        return {"status":"REJECTED","stage":"risk_engine","risk":r}

    if config.EXECUTION_MODE == "paper":
        path = Path(config.STATE_DIR)/f"risk_{asset}.json"
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(r),encoding="utf-8")
        return paper_execution.open_position(path)

    if config.EXECUTION_MODE == "okx_demo":
        return execution_router.open_trade(decision,r)

    return {"status":"REJECTED","reason":"UNKNOWN_EXECUTION_MODE"}

if __name__=="__main__":
    if sys.argv[1] == "prepare":
        print(json.dumps(prepare(sys.argv[2].upper(), int(sys.argv[3]) if len(sys.argv)>3 else 12),ensure_ascii=False))
    else:
        print(json.dumps(execute(json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))),ensure_ascii=False))

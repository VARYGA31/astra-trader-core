#!/usr/bin/env python3
import sys, json
from pathlib import Path
from datetime import datetime, timezone

import config, cooldown, decision_context, paper_execution, risk_engine, decision_gate
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
        "loss_streak_pause":performance_guard.status(),
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

def _correlation_guard(decision, account):
    if not config.BLOCK_BTC_ETH_SAME_DIRECTION:
        return {"blocked":False}

    asset = str(decision.get("asset","")).upper()
    action = str(decision.get("action","")).upper()
    if asset not in {"BTC","ETH"} or action not in {"LONG","SHORT"}:
        return {"blocked":False}

    other = "ETH" if asset == "BTC" else "BTC"
    for p in account.get("exchange_positions", []):
        if p.get("asset") == other and str(p.get("side","")).upper() == action:
            return {
                "blocked":True,
                "reason":"BTC_ETH_SAME_DIRECTION_CORRELATION_BLOCK",
                "other_asset":other,
                "other_side":action,
            }
    return {"blocked":False}

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
    if g.get("loss_streak_pause",{}).get("active"):
        return {"status":"REJECTED","reason":"LOSS_STREAK_PAUSE","guard":g.get("loss_streak_pause")}
    if g.get("trading_halted"):
        return {"status":"REJECTED","reason":"TRADING_HALTED"}
    if config.ONE_POSITION_PER_ASSET and g.get("asset_already_open"):
        return {"status":"REJECTED","reason":"ASSET_ALREADY_HAS_OPEN_POSITION"}

    # Re-check 4H -> 1H -> 15M alignment using FRESH data immediately before execution.
    mtf = mtf_gate.evaluate(p)
    if not mtf.get("passed"):
        return {
            "status":"REJECTED",
            "reason":"MTF_NOT_ALIGNED_AT_EXECUTION",
            "stage":"entry_quality",
            "mtf":mtf,
        }
    if mtf.get("direction") != action:
        return {
            "status":"REJECTED",
            "reason":"ASTRA_DIRECTION_DISAGREES_WITH_MTF",
            "stage":"entry_quality",
            "mtf":mtf,
            "astra_action":action,
        }

    chase = decision_gate.entry_guard(p, action)
    if chase.get("blocked"):
        return {
            "status":"REJECTED",
            "reason":chase.get("reason"),
            "stage":"entry_quality",
            "chase_guard":chase,
        }

    # We execute MARKET orders. Reject if ASTRA's planned entry drifted too far,
    # then recalc risk/R:R from the current market reference price.
    current_price=p.get("decision_context",{}).get("market",{}).get("spot",{}).get("price")
    try:
        planned=float(decision.get("entry"))
        current=float(current_price)
        drift=abs(current-planned)/current*100
    except Exception:
        return {"status":"REJECTED","reason":"ENTRY_PRICE_UNAVAILABLE"}

    if drift>config.ENTRY_DRIFT_MAX_PCT:
        return {
            "status":"REJECTED",
            "reason":"ENTRY_PRICE_DRIFT",
            "drift_pct":drift,
            "maximum_pct":config.ENTRY_DRIFT_MAX_PCT,
            "planned_entry":planned,
            "current_price":current,
        }

    decision["planned_entry"]=planned
    decision["entry"]=current
    decision["mtf_quality"]=mtf.get("quality")
    decision["mtf_gate"]=mtf

    s = p["account_state"]

    # Freeze a compact forensic snapshot at the exact execution check.
    # This is journaled with the trade and is intentionally compact.
    dc = p.get("decision_context", {})
    market = dc.get("market", {})
    spot = market.get("spot", {})
    perp = market.get("perp_okx", {})
    news = dc.get("news", {})
    decision["execution_context"] = {
        "captured_at_utc":datetime.now(timezone.utc).isoformat(),
        "spot":{
            "price":spot.get("price"),
            "ticker_24h":spot.get("ticker_24h"),
            "indicators":spot.get("indicators"),
            "regimes":spot.get("regimes"),
            "changes_pct":spot.get("changes_pct"),
            "order_book":spot.get("order_book"),
            "trade_flow":spot.get("trade_flow"),
        },
        "perp_okx":{
            "funding_rate":perp.get("funding_rate"),
            "open_interest":perp.get("open_interest"),
        },
        "news":{
            "summary":news.get("summary"),
            "guard":news.get("guard"),
        },
        "account_state":{
            "equity":s.get("equity"),
            "open_positions":s.get("open_positions"),
            "current_exposure_usd":s.get("current_exposure_usd"),
            "open_assets":s.get("open_assets"),
        },
        "entry_quality_guard":chase,
        "mtf_gate":mtf,
        "planned_entry":planned,
        "execution_entry_reference":current,
        "entry_drift_pct":drift,
    }

    # Avoid doubling the same macro bet through BTC+ETH in the same direction.
    corr = _correlation_guard(decision, s)
    if corr.get("blocked"):
        return {
            "status":"REJECTED",
            "reason":corr.get("reason"),
            "stage":"portfolio_correlation",
            "correlation_guard":corr,
        }
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

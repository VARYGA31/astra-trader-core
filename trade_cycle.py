#!/usr/bin/env python3
import sys, json
from pathlib import Path
from datetime import datetime, timezone

import config, cooldown, decision_context, paper_execution, risk_engine, decision_gate, mtf_gate, performance_guard
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

def prepare(asset,hours=12,strategy_mode_name=None):
    active_mode=str(strategy_mode_name or strategy_mode.get_mode()).upper()
    c = decision_context.build(asset,hours)
    s = account_state()
    ts = parse_ts(c.get("market",{}).get("generated_at_utc"))
    age = (datetime.now(timezone.utc)-ts).total_seconds() if ts else 10**9
    guards = {
        **c.get("guards",{}),
        "market_stale":age > config.STALE_MARKET_SECONDS,
        "cooldown":cooldown.status(asset),
        "loss_streak_pause":performance_guard.status(active_mode),
        "trading_halted":s.get("trading_halted",False),
        "asset_already_open":asset in set(s.get("open_assets",[])),
    }
    return {
        "status":"READY_FOR_ASTRA" if c.get("status")=="OK" else "FAILED",
        "asset":asset,
        "decision_context":c,
        "execution_mode":config.EXECUTION_MODE,
        "timeframe":"5m" if active_mode=="SCALP" else config.TRADING_TIMEFRAME,
        "strategy_mode":active_mode,
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

    decision_mode=str(decision.get("strategy_mode") or "NORMAL").upper()
    active_mode=strategy_mode.get_mode()
    if active_mode=="PAUSED":
        return {"status":"REJECTED","reason":"STRATEGY_PAUSED"}
    if decision_mode!=active_mode:
        return {"status":"REJECTED","reason":"MODE_CHANGED_BEFORE_EXECUTION","decision_mode":decision_mode,"active_mode":active_mode}
    decision["timeframe"] = decision.get("timeframe") or ("5m" if decision_mode=="SCALP" else config.TRADING_TIMEFRAME)
    p = prepare(asset,12,decision_mode)
    g = p["guards"]

    if g.get("market_stale") or not g.get("market_ok"):
        return {"status":"REJECTED","reason":"MARKET_DATA_GUARD"}
    if not g.get("news_ok"):
        return {"status":"REJECTED","reason":"NEWS_DATA_GUARD"}
    if not g.get("critical_news_verified"):
        return {"status":"REJECTED","reason":"UNVERIFIED_HIGH_IMPACT_NEWS"}
    if asset=="XAU":
        if not g.get("xau_session_ok",False):
            return {"status":"REJECTED","reason":"XAU_WEEKEND_BLOCK"}
        if not g.get("gold_macro_ok",False):
            return {"status":"REJECTED","reason":"XAU_GOLD_MACRO_DATA_GUARD"}
        if not g.get("gold_macro_primary_ok",False):
            return {"status":"REJECTED","reason":"XAU_PRIMARY_MACRO_NEWS_GUARD"}
    if g.get("cooldown",{}).get("active"):
        return {"status":"REJECTED","reason":"COOLDOWN_ACTIVE"}
    if g.get("loss_streak_pause",{}).get("active"):
        return {"status":"REJECTED","reason":"LOSS_STREAK_PAUSE","guard":g.get("loss_streak_pause")}
    if g.get("trading_halted"):
        return {"status":"REJECTED","reason":"TRADING_HALTED"}
    if config.ONE_POSITION_PER_ASSET and g.get("asset_already_open"):
        return {"status":"REJECTED","reason":"ASSET_ALREADY_HAS_OPEN_POSITION"}

    # Re-check the active strategy with FRESH data immediately before execution.
    if decision_mode=="SCALP":
        mtf=scalp_gate.evaluate(p)
        mtf_reject_reason="SCALP_NOT_ALIGNED_AT_EXECUTION"
        chase=scalp_gate.entry_guard(p,action)
    else:
        mtf=mtf_gate.evaluate(p)
        mtf_reject_reason="MTF_NOT_ALIGNED_AT_EXECUTION"
        chase=decision_gate.entry_guard(p,action)
    if not mtf.get("passed"):
        return {
            "status":"REJECTED",
            "reason":mtf_reject_reason,
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

    if chase.get("blocked"):
        return {
            "status":"REJECTED",
            "reason":chase.get("reason"),
            "stage":"entry_quality",
            "chase_guard":chase,
        }

    # Use the ACTUAL tradable OKX swap price for final risk/R:R sizing.
    # The previous implementation used a spot/reference price, which could differ
    # materially from the perpetual fill and silently degrade reward/risk.
    market_ctx=p.get("decision_context",{}).get("market",{})
    spot_price=market_ctx.get("spot",{}).get("price")
    snapshot_swap_price=market_ctx.get("perp_okx",{}).get("last_price")
    try:
        planned=float(decision.get("entry"))
        if config.EXECUTION_MODE=="okx_demo":
            current=float(OKXDemoAdapter().ticker(asset))
            execution_price_source="OKX_SWAP_LIVE_TICKER"
        else:
            current=float(snapshot_swap_price or spot_price)
            execution_price_source="SNAPSHOT_REFERENCE"
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
            "price_source":execution_price_source,
            "spot_price":spot_price,
            "snapshot_swap_price":snapshot_swap_price,
        }

    decision["planned_entry"]=planned
    decision["entry"]=current
    decision["execution_reference_price"]=current
    decision["execution_price_source"]=execution_price_source
    decision["mtf_quality"]=mtf.get("quality")
    decision["mtf_mode"]="SCALP" if decision_mode=="SCALP" else (mtf.get("mode") or "NORMAL")
    if decision_mode=="SCALP":
        decision["scalp_tier"]=mtf.get("tier") or decision.get("scalp_tier") or "PRIME"
    decision["mtf_gate"]=mtf
    decision["strategy_mode"]=decision_mode

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
        "gold_macro":market.get("gold_macro") if asset=="XAU" else None,
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
        "spot_reference_price":spot_price,
        "snapshot_swap_reference_price":snapshot_swap_price,
        "execution_entry_reference":current,
        "execution_price_source":execution_price_source,
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
        "strategy_mode":decision_mode,
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
        with strategy_mode.RUNTIME_LOCK:
            latest_mode=strategy_mode.get_mode()
            if latest_mode!=decision_mode:
                return {"status":"REJECTED","reason":"MODE_CHANGED_BEFORE_ORDER_SUBMISSION","decision_mode":decision_mode,"active_mode":latest_mode}
            return execution_router.open_trade(decision,r)

    return {"status":"REJECTED","reason":"UNKNOWN_EXECUTION_MODE"}

if __name__=="__main__":
    if sys.argv[1] == "prepare":
        print(json.dumps(prepare(sys.argv[2].upper(), int(sys.argv[3]) if len(sys.argv)>3 else 12),ensure_ascii=False))
    else:
        print(json.dumps(execute(json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))),ensure_ascii=False))

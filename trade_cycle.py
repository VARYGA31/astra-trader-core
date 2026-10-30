#!/usr/bin/env python3
import sys, json, time
from pathlib import Path
from datetime import datetime, timezone

import config, cooldown, decision_context, paper_execution, risk_engine, decision_gate, mtf_gate, performance_guard
import daily_loss_latch
import strategy_mode, scalp_gate, micro_gate
from okx_demo_adapter import OKXDemoAdapter
import execution_router
import demo_ledger
import equity_guard
import okx_position_monitor
import trade_journal

def parse_ts(x):
    try:
        return datetime.fromisoformat((x or "").replace("Z","+00:00"))
    except Exception:
        return None

def _rebase_trainer_levels(decision,current_price):
    """Translate Trainer-generated levels to the live execution reference.

    Trainer levels are ATR/R based, not fixed chart levels. If entry drift is
    already inside the existing hard drift guard, translating all levels by the
    same delta preserves stop distance and exact R:R without loosening risk.
    """
    d=dict(decision or {})
    trainer=bool(d.get("trainer_candidate_id")) or str(d.get("setup_type") or "").upper().startswith("TRAINER")
    if not trainer:
        return d,{"rebased":False,"reason":"NOT_TRAINER"}
    try:
        planned=float(d["entry"]); current=float(current_price)
        stop=float(d["stop_loss"]); tp1=float(d["take_profit_1"]); tp2=float(d["take_profit_2"])
    except Exception:
        return d,{"rebased":False,"reason":"INVALID_LEVELS"}
    delta=current-planned
    original={"entry":planned,"stop_loss":stop,"take_profit_1":tp1,"take_profit_2":tp2}
    d["entry"]=current
    d["stop_loss"]=stop+delta
    d["take_profit_1"]=tp1+delta
    d["take_profit_2"]=tp2+delta
    return d,{
        "rebased":True,
        "reason":"TRAINER_LIVE_REFERENCE",
        "delta":delta,
        "original":original,
        "rebased_levels":{
            "entry":d["entry"],"stop_loss":d["stop_loss"],
            "take_profit_1":d["take_profit_1"],"take_profit_2":d["take_profit_2"],
        },
    }

def account_state():
    if config.EXECUTION_MODE == "okx_demo":
        ledger = demo_ledger.status()
        active = okx_position_monitor.active_summary()
        upl=active.get("unrealized_pnl_usd",0.0 if not active.get("open_positions") else None)
        equity = equity_guard.snapshot(
            ledger,unrealized_pnl=upl,
            exchange_flat=(active.get("raw_open_position_count")==0),
        )
        daily_latch=(daily_loss_latch.observe(
            ledger["initial_equity"],equity.get("daily_pnl"),
            operator_demo_balance_ack_date_utc=equity.get("operator_demo_balance_ack_date_utc"),
        ) if equity.get("verified") else {"latched":True,"reason":"EQUITY_UNVERIFIED"})
        dd=(ledger["initial_equity"]-equity["equity"])/ledger["initial_equity"] if equity.get("verified") else 0.0
        if equity.get("verified") and dd>=config.MAX_DRAWDOWN_PCT:
            demo_ledger.halt_for_mark_to_market_drawdown()
        # Expose the exact entry-stop causes; a healthy worker or verified
        # exchange balance alone does not mean the entry path is open.
        reasons=[]
        if ledger["trading_halted"]:
            reasons.append("PERSISTED_LEDGER_HALT")
        if bool(daily_latch.get("latched")):
            reasons.append("UTC_DAILY_LOSS_LATCH")
        if not equity.get("verified"):
            reasons.append("EQUITY_UNVERIFIED")
        if equity.get("verified") and dd>=config.MAX_DRAWDOWN_PCT:
            reasons.append("MARK_TO_MARKET_DRAWDOWN_LIMIT")
        halt_details={
            "halted":bool(reasons),
            "reasons":reasons,
            "ledger_persisted_halt":bool(ledger["trading_halted"]),
            "ledger_realized_drawdown_pct":round(float(ledger.get("drawdown_pct") or 0)*100,3),
            "max_drawdown_limit_pct":round(config.MAX_DRAWDOWN_PCT*100,3),
            "conservative_equity_drawdown_pct":round(max(0.0,dd)*100,3) if equity.get("verified") else None,
            "daily_loss_latched":bool(daily_latch.get("latched")),
            "daily_loss_latch_reason":daily_latch.get("reason"),
            "daily_loss_latch_date_utc":daily_latch.get("date_utc"),
            "daily_loss_limit_pct":round(config.DAILY_LOSS_LIMIT_PCT*100,3),
            "operator_demo_balance_ack_date_utc":equity.get("operator_demo_balance_ack_date_utc"),
            "operator_demo_balance_ack_offset_usd":equity.get("operator_demo_balance_ack_offset_usd"),
            "raw_account_daily_change_usd":equity.get("account_daily_change"),
            "adjusted_account_daily_change_usd":equity.get("adjusted_account_daily_change"),
            "conservative_daily_pnl_usd":round(float(equity["daily_pnl"]),5) if equity.get("verified") else None,
            "initial_equity_usd":round(float(ledger["initial_equity"]),3),
            "equity_verified":bool(equity.get("verified")),
            "trading_permissions_changed":False,
        }
        return {
            "initial_equity":ledger["initial_equity"],
            "equity":equity.get("equity",ledger["equity"]),
            "daily_pnl":equity.get("daily_pnl",ledger["daily_pnl"]),
            "daily_loss_latched":bool(daily_latch.get("latched")),
            "daily_loss_latch":daily_latch,
            "equity_verified":bool(equity.get("verified")),
            "equity_source":equity.get("source"),
            "equity_error":equity.get("reason"),
            "open_positions":active["open_positions"],
            "current_exposure_usd":active["current_exposure_usd"],
            "open_assets":active.get("assets",[]),
            "exchange_positions":active.get("details",[]),
            "trading_halted":bool(halt_details["halted"]),
            "entry_halt_diagnostics":halt_details,
        }

    s = paper_execution.status()
    return {
        "initial_equity":s.get("initial_equity"),
        "equity":s.get("account_equity"),
        "equity_verified":True,
        "daily_pnl":s.get("daily_realized_pnl",0),
        "open_positions":s.get("open_positions_count",0),
        "current_exposure_usd":s.get("current_exposure_usd",0),
        "open_assets":[],
        "trading_halted":s.get("trading_halted",False),
    }

def prepare(asset,hours=12,strategy_mode_name=None):
    active_mode=str(strategy_mode_name or strategy_mode.get_mode()).upper()
    c = decision_context.build(asset,hours,include_micro=(active_mode=="MICRO"))
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
        "timeframe":"1m" if active_mode=="MICRO" else "5m" if active_mode in {"SCALP","AUTO"} else config.TRADING_TIMEFRAME,
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
    if asset in config.DISABLED_ENTRY_ASSETS:
        return {"status":"REJECTED","reason":"ASSET_NEW_ENTRIES_DISABLED"}
    if not config.MICRO_NEW_ENTRIES_ENABLED and str(decision.get("strategy_mode") or "").upper() == "MICRO":
        return {"status":"REJECTED","reason":"MICRO_DISABLED"}

    decision_mode=str(decision.get("strategy_mode") or "NORMAL").upper()
    active_mode=strategy_mode.get_mode()
    if active_mode=="PAUSED":
        return {"status":"REJECTED","reason":"STRATEGY_PAUSED"}
    adaptive_active = bool(decision.get("adaptive_mode")) and active_mode=="AUTO"
    if not adaptive_active and decision_mode!=active_mode:
        return {"status":"REJECTED","reason":"MODE_CHANGED_BEFORE_EXECUTION","decision_mode":decision_mode,"active_mode":active_mode}
    decision["timeframe"] = decision.get("timeframe") or ("1m" if decision_mode=="MICRO" else "5m" if decision_mode=="SCALP" else config.TRADING_TIMEFRAME)
    p = prepare(asset,12,decision_mode)
    g = p["guards"]

    if not p["account_state"].get("equity_verified",False):
        return {"status":"REJECTED","reason":"OKX_EQUITY_UNAVAILABLE","stage":"account_equity"}

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

    # Re-check FRESH market data immediately before execution.
    #
    # NORMAL/SCALP manual modes still require the deterministic alignment gate.
    # AUTO/ADAPTIVE deliberately does not: the model saw the full market package
    # and selected the strategy. Python still keeps hard anti-chase, spread,
    # risk, exposure, R:R and execution-quality protections.
    if decision_mode=="MICRO":
        mtf=micro_gate.evaluate(p)
        mtf_reject_reason="MICRO_NOT_ALIGNED_AT_EXECUTION"
        chase=micro_gate.entry_guard(p,action)
    elif decision_mode=="SCALP":
        mtf=scalp_gate.evaluate(p)
        mtf_reject_reason="SCALP_NOT_ALIGNED_AT_EXECUTION"
        chase=scalp_gate.entry_guard(p,action)
    else:
        mtf=mtf_gate.evaluate(p)
        mtf_reject_reason="MTF_NOT_ALIGNED_AT_EXECUTION"
        chase=decision_gate.entry_guard(p,action)

    if not adaptive_active:
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

    if adaptive_active:
        perp_now=p.get("decision_context",{}).get("market",{}).get("perp_okx",{})
        try:
            bid=float(perp_now.get("bid_price")); ask=float(perp_now.get("ask_price"))
            mid=(bid+ask)/2
            spread_pct=(ask-bid)/mid*100 if mid>0 and ask>=bid else None
        except Exception:
            spread_pct=None
        spread_max=(
            config.ADAPTIVE_SCALP_MAX_SPREAD_PCT
            if decision_mode=="SCALP"
            else config.ADAPTIVE_NORMAL_MAX_SPREAD_PCT
        )
        if spread_pct is None or spread_pct>spread_max:
            return {
                "status":"REJECTED",
                "reason":"ADAPTIVE_SPREAD_GUARD",
                "stage":"entry_quality",
                "spread_pct":spread_pct,
                "maximum_pct":spread_max,
            }

    # Use the ACTUAL tradable OKX swap price for final risk/R:R sizing.
    # The previous implementation used a spot/reference price, which could differ
    # materially from the perpetual fill and silently degrade reward/risk.
    market_ctx=p.get("decision_context",{}).get("market",{})
    spot_price=market_ctx.get("spot",{}).get("price")
    snapshot_swap_price=market_ctx.get("perp_okx",{}).get("last_price")
    snapshot_at_utc=market_ctx.get("generated_at_utc")
    planned_raw=decision.get("entry")
    try:
        planned=float(planned_raw)
    except Exception as e:
        return {
            "status":"REJECTED",
            "reason":"ENTRY_PRICE_UNAVAILABLE",
            "stage":"PLANNED_ENTRY_PARSE",
            "error_type":type(e).__name__,
            "error":str(e)[:500],
            "planned_entry_raw":planned_raw,
            "snapshot_swap_price":snapshot_swap_price,
            "snapshot_at_utc":snapshot_at_utc,
            "model_started_at_utc":decision.get("_model_started_at_utc"),
            "model_finished_at_utc":decision.get("_model_finished_at_utc"),
            "model_latency_ms":decision.get("_model_latency_ms"),
        }

    ticker_started_at_utc=datetime.now(timezone.utc).isoformat()
    ticker_t0=time.monotonic()
    try:
        if config.EXECUTION_MODE=="okx_demo":
            adapter=OKXDemoAdapter()
            current,execution_price_source=adapter.ticker_with_source(asset)
            current=float(current)
        else:
            current=float(snapshot_swap_price or spot_price)
            execution_price_source="SNAPSHOT_REFERENCE"
        ticker_latency_ms=round((time.monotonic()-ticker_t0)*1000.0,2)
        ticker_finished_at_utc=datetime.now(timezone.utc).isoformat()
        drift=abs(current-planned)/current*100
    except Exception as e:
        return {
            "status":"REJECTED",
            "reason":"ENTRY_PRICE_UNAVAILABLE",
            "stage":"OKX_FRESH_TICKER" if config.EXECUTION_MODE=="okx_demo" else "SNAPSHOT_REFERENCE_PARSE",
            "error_type":type(e).__name__,
            "error":str(e)[:500],
            "planned_entry":planned,
            "snapshot_swap_price":snapshot_swap_price,
            "snapshot_at_utc":snapshot_at_utc,
            "ticker_started_at_utc":ticker_started_at_utc,
            "ticker_latency_ms":round((time.monotonic()-ticker_t0)*1000.0,2),
            "model_started_at_utc":decision.get("_model_started_at_utc"),
            "model_finished_at_utc":decision.get("_model_finished_at_utc"),
            "model_latency_ms":decision.get("_model_latency_ms"),
        }

    if drift>config.ENTRY_DRIFT_MAX_PCT:
        return {
            "status":"REJECTED",
            "reason":"ENTRY_PRICE_DRIFT",
            "stage":"ENTRY_DRIFT_GUARD",
            "drift_pct":drift,
            "maximum_pct":config.ENTRY_DRIFT_MAX_PCT,
            "planned_entry":planned,
            "current_price":current,
            "price_source":execution_price_source,
            "spot_price":spot_price,
            "snapshot_swap_price":snapshot_swap_price,
            "snapshot_at_utc":snapshot_at_utc,
            "ticker_started_at_utc":ticker_started_at_utc,
            "ticker_finished_at_utc":ticker_finished_at_utc,
            "ticker_latency_ms":ticker_latency_ms,
            "model_started_at_utc":decision.get("_model_started_at_utc"),
            "model_finished_at_utc":decision.get("_model_finished_at_utc"),
            "model_latency_ms":decision.get("_model_latency_ms"),
        }

    decision["planned_entry"]=planned
    decision,rebase_info=_rebase_trainer_levels(decision,current) if adaptive_active else (decision,{"rebased":False,"reason":"NOT_ADAPTIVE"})
    if not rebase_info.get("rebased"):
        decision["entry"]=current
    decision["execution_reference_price"]=current
    decision["trainer_rebase"]=rebase_info
    decision["execution_price_source"]=execution_price_source
    if adaptive_active:
        decision["mtf_quality"]=float(decision.get("adaptive_setup_quality") or decision.get("mtf_quality") or 0)
        decision["mtf_mode"]="SCALP" if decision_mode=="SCALP" else "NORMAL"
    else:
        decision["mtf_quality"]=mtf.get("quality")
        decision["mtf_mode"]="MICRO" if decision_mode=="MICRO" else "SCALP" if decision_mode=="SCALP" else (mtf.get("mode") or "NORMAL")
    if decision_mode=="SCALP":
        decision["scalp_tier"]=(decision.get("scalp_tier") or mtf.get("tier") or "FAST") if adaptive_active else (mtf.get("tier") or decision.get("scalp_tier") or "PRIME")
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
        "snapshot_at_utc":snapshot_at_utc,
        "model_started_at_utc":decision.get("_model_started_at_utc"),
        "model_finished_at_utc":decision.get("_model_finished_at_utc"),
        "model_latency_ms":decision.get("_model_latency_ms"),
        "ticker_started_at_utc":ticker_started_at_utc,
        "ticker_finished_at_utc":ticker_finished_at_utc,
        "ticker_latency_ms":ticker_latency_ms,
        "trainer_rebase":decision.get("trainer_rebase"),
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
        "daily_loss_latched":bool(s.get("daily_loss_latched")),
        "open_positions":s["open_positions"],
        "current_exposure_usd":s["current_exposure_usd"],
        "asset_already_open":g.get("asset_already_open",False),
        "critical_news_verified":bool(g.get("critical_news_verified")),
        "strategy_mode":decision_mode,
    }
    # Passive evidence collection; this must never veto or modify Risk Engine.
    try:
        import normal_stop_shadow
        stop_audit=normal_stop_shadow.examine(rinput)
        if stop_audit:
            trade_journal.append_event({"event":"NORMAL_STOP_DISTANCE_SHADOW",**stop_audit})
    except Exception:
        pass
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
            if not (bool(decision.get("adaptive_mode")) and latest_mode=="AUTO") and latest_mode!=decision_mode:
                return {"status":"REJECTED","reason":"MODE_CHANGED_BEFORE_ORDER_SUBMISSION","decision_mode":decision_mode,"active_mode":latest_mode}
            return execution_router.open_trade(decision,r)

    return {"status":"REJECTED","reason":"UNKNOWN_EXECUTION_MODE"}

if __name__=="__main__":
    if sys.argv[1] == "prepare":
        print(json.dumps(prepare(sys.argv[2].upper(), int(sys.argv[3]) if len(sys.argv)>3 else 12),ensure_ascii=False))
    else:
        print(json.dumps(execute(json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))),ensure_ascii=False))

#!/usr/bin/env python3
from datetime import datetime, timezone
import time

import config
import telegram_notifier
import trade_journal
import demo_ledger
from okx_demo_adapter import OKXDemoAdapter
import okx_position_monitor
import execution_quality

def open_trade(decision, risk):
    if config.EXECUTION_MODE == "paper":
        return {"status":"ROUTER_PAPER","note":"paper execution handled by trade_cycle"}

    if config.EXECUTION_MODE != "okx_demo":
        return {"status":"REJECTED","reason":"UNKNOWN_EXECUTION_MODE"}

    adapter = OKXDemoAdapter()
    asset = decision["asset"]
    action = str(decision.get("action","")).upper()
    mtf_mode = str(decision.get("mtf_mode") or "NORMAL").upper()
    strategy_mode = str(decision.get("strategy_mode") or ("SCALP" if mtf_mode=="SCALP" else "NORMAL")).upper()
    scalp_tier = str(risk.get("scalp_tier") or decision.get("scalp_tier") or "PRIME").upper() if strategy_mode=="SCALP" else None

    # FINAL exchange-side portfolio guard immediately before order submission.
    summary = adapter.exchange_active_summary()

    if config.ONE_POSITION_PER_ASSET and asset in set(summary.get("assets", [])):
        return {"status":"REJECTED","reason":"ASSET_ALREADY_HAS_OPEN_POSITION_EXCHANGE"}

    max_open_positions = config.MICRO_MAX_OPEN_POSITIONS if strategy_mode=="MICRO" else config.MAX_OPEN_POSITIONS
    if int(summary.get("open_positions", 0)) >= max_open_positions:
        return {
            "status":"REJECTED",
            "reason":"MAX_OPEN_POSITIONS_EXCHANGE_GUARD",
            "exchange_summary":summary,
            "maximum":max_open_positions,
        }

    if config.BLOCK_BTC_ETH_SAME_DIRECTION and asset in {"BTC","ETH"}:
        other = "ETH" if asset == "BTC" else "BTC"
        for p in summary.get("details", []):
            if p.get("asset") == other and str(p.get("side","")).upper() == action:
                return {
                    "status":"REJECTED",
                    "reason":"BTC_ETH_SAME_DIRECTION_EXCHANGE_GUARD",
                    "other_position":p,
                }

    ledger = demo_ledger.status()
    equity = float(ledger.get("equity") or config.INITIAL_EQUITY)
    exposure_now = float(summary.get("current_exposure_usd", 0))
    proposed = float(risk.get("position_notional_usd", 0))
    exposure_cap_pct = config.MICRO_MAX_TOTAL_EXPOSURE_PCT if strategy_mode=="MICRO" else config.MAX_TOTAL_EXPOSURE_PCT
    exposure_cap = equity * exposure_cap_pct

    if exposure_now + proposed > exposure_cap + 1e-9:
        return {
            "status":"REJECTED",
            "reason":"MAX_TOTAL_EXPOSURE_EXCHANGE_GUARD",
            "current_exposure_usd":exposure_now,
            "proposed_notional_usd":proposed,
            "exposure_cap_usd":exposure_cap,
        }

    # ----- Execution quality guard -----
    # Execution v4.1 uses the actual executable touch, not the last trade:
    # LONG -> ask, SHORT -> bid. A last-trade reference can be non-marketable
    # and caused repeated safe FOK cancellations in production.
    min_tp1_r, min_tp2_r = execution_quality.min_rr_for_mode(mtf_mode,scalp_tier)

    if config.OKX_ENTRY_ORDER_TYPE != "fok":
        return {
            "status":"REJECTED",
            "reason":"UNSAFE_ENTRY_ORDER_TYPE",
            "configured_order_type":config.OKX_ENTRY_ORDER_TYPE,
            "required_order_type":"fok",
        }

    attempts=[]
    opened=None
    quality_guard=None
    pre_order_reference=None
    pre_order_quote=None
    max_attempts=max(1,min(3,int(config.OKX_ENTRY_FOK_MAX_ATTEMPTS)))

    for attempt_no in range(1,max_attempts+1):
        pre_order_quote=adapter.executable_quote(asset,action)
        pre_order_reference=float(pre_order_quote["reference"])

        quality_guard=execution_quality.build_entry_guard(
            asset=asset,
            action=action,
            reference=pre_order_reference,
            stop=risk["stop_loss"],
            tp1=risk["take_profit_1"],
            tp2=risk["take_profit_2"],
            mode=mtf_mode,
            scalp_tier=scalp_tier,
        )

        if config.EXECUTION_QUALITY_ENABLED and not quality_guard.get("passed"):
            return {
                "status":"REJECTED",
                "reason":"PRE_ORDER_EXECUTION_QUALITY",
                "stage":"execution_quality",
                "execution_quality":quality_guard,
                "planned_entry":decision.get("planned_entry"),
                "risk_engine_entry":risk.get("entry"),
                "pre_order_reference":pre_order_reference,
                "pre_order_quote":pre_order_quote,
                "entry_attempts":attempts,
            }

        # The FOK price is the WORST fill we permit. It combines:
        # 1) max adverse slippage and 2) minimum R:R after fill.
        raw_limit=(
            quality_guard.get("raw_fok_limit_price")
            if config.EXECUTION_QUALITY_ENABLED
            else pre_order_reference
        )
        rounded_limit=float(adapter.normalize_entry_limit_price(asset,action,raw_limit))

        opened=adapter.open_fok(
            asset,
            action,
            risk["position_notional_usd"],
            risk["leverage"],
            risk["stop_loss"],
            risk["take_profit_1"],
            risk["take_profit_2"],
            rounded_limit,
            pre_order_reference,
        )
        attempts.append({
            "attempt":attempt_no,
            "reference":pre_order_reference,
            "reference_side":pre_order_quote.get("reference_side"),
            "bid":pre_order_quote.get("bid"),
            "ask":pre_order_quote.get("ask"),
            "spread_pct":pre_order_quote.get("spread_pct"),
            "limit_price":opened.get("limit_price"),
            "order_id":opened.get("order_id"),
            "order_state":opened.get("order_state"),
            "filled":bool(opened.get("filled")),
        })

        if opened.get("filled"):
            break

        if attempt_no<max_attempts:
            time.sleep(max(0,int(config.OKX_ENTRY_FOK_RETRY_DELAY_MS))/1000.0)

    if not opened or not opened.get("filled"):
        return {
            "status":"NO_TRADE",
            "reason":"ENTRY_FOK_NOT_FILLED",
            "stage":"execution_quality",
            "order_id":(opened or {}).get("order_id"),
            "order_state":(opened or {}).get("order_state"),
            "requested_qty_contracts":(opened or {}).get("requested_qty_contracts"),
            "filled_qty_contracts":(opened or {}).get("qty_contracts"),
            "pre_order_reference":pre_order_reference,
            "pre_order_quote":pre_order_quote,
            "entry_limit_price":(opened or {}).get("limit_price"),
            "execution_quality":quality_guard,
            "entry_attempts":attempts,
        }

    entry = float(opened["entry"])
    post_fill = execution_quality.audit_fill(
        asset=asset,
        action=action,
        reference=pre_order_reference,
        fill=entry,
        stop=risk["stop_loss"],
        tp1=risk["take_profit_1"],
        tp2=risk["take_profit_2"],
        mode=mtf_mode,
        scalp_tier=scalp_tier,
    )

    # This should be mathematically unreachable with a correctly respected FOK
    # limit, but retain a failsafe in case of exchange/API edge cases.
    if config.EXECUTION_QUALITY_ENABLED and not post_fill.get("passed"):
        cleanup={"status":"NOT_ATTEMPTED"}
        close_result={"status":"NOT_ATTEMPTED"}
        if config.POST_FILL_FAILSAFE_CLOSE:
            cleanup=adapter.cancel_attached_algos(asset, opened["order_id"])
            try:
                c=adapter.close_market(asset, action, opened["qty_contracts"])
                row=(c.get("data") or [{}])[0]
                close_ord=row.get("ordId")
                terminal=adapter.wait_filled(asset,close_ord,timeout=15) if close_ord else None
                close_result={
                    "status":"CLOSE_REQUESTED",
                    "order_id":close_ord,
                    "terminal_state":(terminal or {}).get("state"),
                    "avgPx":(terminal or {}).get("avgPx"),
                }
            except Exception as e:
                close_result={"status":"FAILED","error":str(e)}

        event={
            "event":"OKX_ENTRY_EXECUTION_ABORTED",
            "asset":asset,
            "side":action,
            "order_id":opened.get("order_id"),
            "entry":entry,
            "pre_order_reference":pre_order_reference,
            "entry_limit_price":opened.get("limit_price"),
            "execution_quality":post_fill,
            "algo_cleanup":cleanup,
            "failsafe_close":close_result,
            "timestamp_utc":datetime.now(timezone.utc).isoformat(),
        }
        trade_journal.append_event(event)
        return {
            "status":"REJECTED",
            "reason":"POST_FILL_EXECUTION_QUALITY_FAIL",
            "stage":"execution_quality",
            "execution_quality":post_fill,
            "algo_cleanup":cleanup,
            "failsafe_close":close_result,
        }

    notional = opened["position_value_usd_approx"]
    protection = opened.get("protection", {})

    record = {
        "asset":asset,
        "inst_id":opened["inst_id"],
        "side":action,
        "timeframe":decision.get("timeframe") or config.TRADING_TIMEFRAME,
        "entry":entry,
        "planned_entry":decision.get("planned_entry"),
        "risk_engine_entry":risk.get("entry"),
        "pre_order_reference":pre_order_reference,
        "pre_order_quote":pre_order_quote,
        "entry_attempts":attempts,
        "entry_order_type":"FOK_LIMIT",
        "entry_reference_mode":"EXECUTABLE_TOUCH_V4_1",
        "entry_limit_price":opened.get("limit_price"),
        "fill_slippage_pct":post_fill.get("adverse_slippage_pct"),
        "fill_delta_pct":post_fill.get("fill_delta_pct"),
        "qty_contracts":opened["qty_contracts"],
        "last_qty_contracts":opened["qty_contracts"],
        "notional_usd":notional,
        "remaining_notional_usd":notional,
        "margin_usd":notional/opened["leverage"] if opened["leverage"] else None,
        "leverage":opened["leverage"],
        "stop_loss":risk["stop_loss"],
        "take_profit_1":risk["take_profit_1"],
        "take_profit_2":risk["take_profit_2"],
        "planned_tp1_r":risk.get("tp1_r"),
        "planned_tp2_r":risk.get("tp2_r"),
        "tp1_r":post_fill.get("tp1_r"),
        "tp2_r":post_fill.get("tp2_r"),
        "minimum_tp1_r_at_fill":min_tp1_r,
        "minimum_tp2_r_at_fill":min_tp2_r,
        "execution_quality":post_fill,
        "order_id":opened["order_id"],
        "opened_at_utc":datetime.now(timezone.utc).isoformat(),
        "tp1_taken":False,
        "protection_mode":protection.get("mode"),
        "tp1_qty_contracts":protection.get("tp1_qty_contracts"),
        "tp2_qty_contracts":protection.get("tp2_qty_contracts"),
        "mode":"OKX DEMO",
        "strategy_mode":strategy_mode,
        "decision_source":"ADAPTIVE_V1" if decision.get("adaptive_mode") else "LEGACY_GATE",
        "adaptive_mode":bool(decision.get("adaptive_mode")),
        "scalp_tier":scalp_tier,
        "confidence":decision.get("confidence"),
        "decision_reason":decision.get("reason"),
        "data_quality":decision.get("data_quality"),
        "volatility_regime":decision.get("volatility_regime"),
        "gate":decision.get("gate"),
        "setup_type":decision.get("setup_type"),
        "mtf_mode":mtf_mode,
        "mtf_quality":risk.get("mtf_quality"),
        "trade_quality":risk.get("trade_quality"),
        "risk_pct_budget":risk.get("risk_pct_budget"),
        "execution_context":decision.get("execution_context"),
    }

    okx_position_monitor.register_trade(record)
    trade_journal.append_event({"event":"OKX_POSITION_OPENED", **record})
    telegram_notifier.notify_open(record)
    return {
        "status":"OKX_DEMO_OPENED",
        "trade":record,
        "exchange_protection":protection,
        "execution_quality":post_fill,
    }

def sync_positions():
    if config.EXECUTION_MODE == "okx_demo":
        return okx_position_monitor.check_once()
    return {"status":"SKIPPED","reason":"PAPER_MODE"}

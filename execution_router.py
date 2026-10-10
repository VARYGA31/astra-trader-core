#!/usr/bin/env python3
from datetime import datetime, timezone

import config
import telegram_notifier
import trade_journal
import demo_ledger
from okx_demo_adapter import OKXDemoAdapter
import okx_position_monitor

def open_trade(decision, risk):
    if config.EXECUTION_MODE == "paper":
        return {"status":"ROUTER_PAPER","note":"paper execution handled by trade_cycle"}

    if config.EXECUTION_MODE != "okx_demo":
        return {"status":"REJECTED","reason":"UNKNOWN_EXECUTION_MODE"}

    adapter = OKXDemoAdapter()
    asset = decision["asset"]

    # FINAL exchange-side portfolio guard immediately before order submission.
    # OKX is the source of truth here; this prevents stale/raced account snapshots
    # from creating a 3rd position or exceeding the global exposure cap.
    summary = adapter.exchange_active_summary()

    if config.ONE_POSITION_PER_ASSET and asset in set(summary.get("assets", [])):
        return {"status":"REJECTED","reason":"ASSET_ALREADY_HAS_OPEN_POSITION_EXCHANGE"}

    if int(summary.get("open_positions", 0)) >= config.MAX_OPEN_POSITIONS:
        return {
            "status":"REJECTED",
            "reason":"MAX_OPEN_POSITIONS_EXCHANGE_GUARD",
            "exchange_summary":summary,
        }

    # Final BTC/ETH same-direction correlation guard.
    if config.BLOCK_BTC_ETH_SAME_DIRECTION and asset in {"BTC","ETH"}:
        other = "ETH" if asset == "BTC" else "BTC"
        for p in summary.get("details", []):
            if p.get("asset") == other and str(p.get("side","")).upper() == str(decision.get("action","")).upper():
                return {
                    "status":"REJECTED",
                    "reason":"BTC_ETH_SAME_DIRECTION_EXCHANGE_GUARD",
                    "other_position":p,
                }

    ledger = demo_ledger.status()
    equity = float(ledger.get("equity") or config.INITIAL_EQUITY)
    exposure_now = float(summary.get("current_exposure_usd", 0))
    proposed = float(risk.get("position_notional_usd", 0))
    exposure_cap = equity * config.MAX_TOTAL_EXPOSURE_PCT

    if exposure_now + proposed > exposure_cap + 1e-9:
        return {
            "status":"REJECTED",
            "reason":"MAX_TOTAL_EXPOSURE_EXCHANGE_GUARD",
            "current_exposure_usd":exposure_now,
            "proposed_notional_usd":proposed,
            "exposure_cap_usd":exposure_cap,
        }

    opened = adapter.open_market(
        asset,
        decision["action"],
        risk["position_notional_usd"],
        risk["leverage"],
        risk["stop_loss"],
        risk["take_profit_1"],
        risk["take_profit_2"],
    )

    entry = opened["entry"]
    notional = opened["position_value_usd_approx"]
    protection = opened.get("protection", {})

    record = {
        "asset":asset,
        "inst_id":opened["inst_id"],
        "side":decision["action"],
        "timeframe":decision.get("timeframe") or config.TRADING_TIMEFRAME,
        "entry":entry,
        "qty_contracts":opened["qty_contracts"],
        "last_qty_contracts":opened["qty_contracts"],
        "notional_usd":notional,
        "remaining_notional_usd":notional,
        "margin_usd":notional/opened["leverage"] if opened["leverage"] else None,
        "leverage":opened["leverage"],
        "stop_loss":risk["stop_loss"],
        "take_profit_1":risk["take_profit_1"],
        "take_profit_2":risk["take_profit_2"],
        "tp1_r":risk.get("tp1_r"),
        "tp2_r":risk.get("tp2_r"),
        "order_id":opened["order_id"],
        "opened_at_utc":datetime.now(timezone.utc).isoformat(),
        "tp1_taken":False,
        "protection_mode":protection.get("mode"),
        "tp1_qty_contracts":protection.get("tp1_qty_contracts"),
        "tp2_qty_contracts":protection.get("tp2_qty_contracts"),
        "mode":"OKX DEMO",
        # Persist the actual decision/audit data so future losses can be diagnosed
        # even after /health has been overwritten by newer decisions.
        "confidence":decision.get("confidence"),
        "decision_reason":decision.get("reason"),
        "data_quality":decision.get("data_quality"),
        "volatility_regime":decision.get("volatility_regime"),
        "gate":decision.get("gate"),
        "setup_type":decision.get("setup_type"),
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
    }

def sync_positions():
    if config.EXECUTION_MODE == "okx_demo":
        return okx_position_monitor.check_once()
    return {"status":"SKIPPED","reason":"PAPER_MODE"}

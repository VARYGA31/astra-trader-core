#!/usr/bin/env python3
import json
from datetime import datetime, timezone
from pathlib import Path

import config
import decision_gate
import market_snapshot
from okx_demo_adapter import OKXDemoAdapter
import okx_position_monitor
import telegram_notifier
from exit_news_decider import decide_news_exit

STATE = Path(config.STATE_DIR) / "emergency_exit_state.json"
NEWS_SEEN = Path(config.STATE_DIR) / "emergency_news_seen.json"

def _load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    t = path.with_suffix(".tmp")
    t.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    t.replace(path)

def _position_side(position):
    try:
        return "LONG" if float(position.get("pos") or 0) > 0 else "SHORT"
    except Exception:
        return None

def _market_reversal_details(side, spot):
    score, reasons = decision_gate.score_spot(spot)
    ind = spot.get("indicators", {})
    ch = spot.get("changes_pct", {})
    flow = spot.get("trade_flow", {})
    book = spot.get("order_book", {})
    price = spot.get("price")
    ema20 = ind.get("ema20")
    ratio = flow.get("buy_sell_ratio")
    imb = book.get("imbalance")
    one_h = ch.get("1h")
    momentum = spot.get("regimes", {}).get("momentum")

    if side == "SHORT":
        components = {
            "price_above_ema20": isinstance(price,(int,float)) and isinstance(ema20,(int,float)) and price > ema20,
            "bullish_momentum": momentum == "BULLISH",
            "aggressive_buy_flow": isinstance(ratio,(int,float)) and ratio >= 1.20,
            "positive_1h": isinstance(one_h,(int,float)) and one_h >= .35,
            "bid_imbalance": isinstance(imb,(int,float)) and imb >= .15,
        }
        opposite = score >= config.EMERGENCY_MARKET_EXIT_SCORE
        immediate = score >= config.EMERGENCY_MARKET_IMMEDIATE_SCORE
    else:
        components = {
            "price_below_ema20": isinstance(price,(int,float)) and isinstance(ema20,(int,float)) and price < ema20,
            "bearish_momentum": momentum == "BEARISH",
            "aggressive_sell_flow": isinstance(ratio,(int,float)) and ratio <= .83,
            "negative_1h": isinstance(one_h,(int,float)) and one_h <= -.35,
            "ask_imbalance": isinstance(imb,(int,float)) and imb <= -.15,
        }
        opposite = score <= -config.EMERGENCY_MARKET_EXIT_SCORE
        immediate = score <= -config.EMERGENCY_MARKET_IMMEDIATE_SCORE

    confirmations = sum(1 for v in components.values() if v)
    return {
        "score":score,
        "score_reasons":reasons,
        "components":components,
        "component_confirmations":confirmations,
        "opposite_score":opposite,
        "immediate_score":immediate,
    }

def _submit_forced_close(asset, reason, details):
    adapter = OKXDemoAdapter()
    pos = adapter.get_position(asset)
    if not pos:
        return {"status":"NO_POSITION","asset":asset}

    rec = okx_position_monitor.load().get(asset, {})
    side = str(rec.get("side") or _position_side(pos) or "").upper()
    if side not in {"LONG","SHORT"}:
        return {"status":"FAILED","reason":"UNKNOWN_POSITION_SIDE","asset":asset}

    qty = abs(float(pos.get("pos") or 0))
    okx_position_monitor.mark_forced_close(asset, reason, details)

    submit = adapter.close_market(asset, side, qty)
    telegram_notifier.notify_system(
        f"EMERGENCY EXIT отправлен: {asset} {side}. Причина: {reason}. "
        f"Позиция закрывается reduce-only market-ордером.",
        level="RISK",
    )
    return {
        "status":"CLOSE_SUBMITTED",
        "asset":asset,
        "side":side,
        "qty_contracts":qty,
        "reason":reason,
        "details":details,
        "okx_submit":submit,
    }

def check_market_exits(dry_run=False):
    if config.EXECUTION_MODE != "okx_demo":
        return {"status":"SKIPPED","reason":"NOT_OKX_DEMO"}
    if not config.EMERGENCY_EXIT_ENABLED and not dry_run:
        return {"status":"DISABLED"}

    adapter = OKXDemoAdapter()
    summary = adapter.exchange_active_summary()
    state = _load(STATE)
    results = []

    for d in summary.get("details", []):
        asset = d.get("asset")
        side = str(d.get("side","")).upper()
        if side not in {"LONG","SHORT"}:
            continue

        market = market_snapshot.snapshot(asset)
        if market.get("data_quality",{}).get("status") == "FAILED":
            results.append({"asset":asset,"status":"MARKET_DATA_FAILED"})
            continue

        rev = _market_reversal_details(side, market.get("spot", {}))
        key = f"{asset}:{side}"
        old_count = int(state.get(key, {}).get("count", 0))

        # Require at least 2 concrete opposite-market components.
        qualified = rev["opposite_score"] and rev["component_confirmations"] >= 2
        if qualified:
            count = old_count + 1
        else:
            count = 0

        state[key] = {
            "count":count,
            "last_checked_utc":datetime.now(timezone.utc).isoformat(),
            "last_details":rev,
        }

        should_close = (
            qualified
            and (
                rev["immediate_score"]
                or count >= config.EMERGENCY_MARKET_CONFIRMATIONS
            )
        )

        item = {
            "asset":asset,
            "side":side,
            "status":"OPPOSITE_MARKET" if qualified else "HELD",
            "confirmation_count":count,
            "would_close":should_close,
            "reversal":rev,
        }

        if should_close and not dry_run:
            item["close"] = _submit_forced_close(
                asset,
                "EMERGENCY_OPPOSITE_MARKET",
                rev,
            )
            state[key]["count"] = 0
        results.append(item)

    _save(STATE, state)
    return {"status":"OK","dry_run":dry_run,"results":results}

def _event_age_minutes(event):
    try:
        dt = datetime.fromisoformat((event.get("published_at_utc") or "").replace("Z","+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() / 60.0
    except Exception:
        return None

def on_verified_news_event(event, dry_run=False):
    if config.EXECUTION_MODE != "okx_demo":
        return {"status":"SKIPPED","reason":"NOT_OKX_DEMO"}
    if not config.EMERGENCY_EXIT_ENABLED and not dry_run:
        return {"status":"DISABLED"}

    if event.get("impact_hint") != "HIGH" or not event.get("trade_usable"):
        return {"status":"IGNORED","reason":"NOT_VERIFIED_HIGH_IMPACT"}

    age = _event_age_minutes(event)
    if age is None or age > config.EMERGENCY_NEWS_MAX_AGE_MINUTES:
        return {"status":"IGNORED","reason":"NEWS_TOO_OLD","age_minutes":age}

    asset = str(event.get("asset","")).upper()
    if asset not in config.ALLOWED_ASSETS:
        return {"status":"IGNORED","reason":"ASSET_NOT_ALLOWED"}

    seen = _load(NEWS_SEEN)
    key = f"{asset}:{event.get('id')}"
    if key in seen and not dry_run:
        return {"status":"IGNORED","reason":"NEWS_ALREADY_REVIEWED"}

    adapter = OKXDemoAdapter()
    pos = adapter.get_position(asset)
    if not pos:
        if not dry_run:
            seen[key] = {"status":"NO_POSITION","at_utc":datetime.now(timezone.utc).isoformat()}
            _save(NEWS_SEEN, seen)
        return {"status":"NO_POSITION","asset":asset}

    rec = okx_position_monitor.load().get(asset, {})
    side = str(rec.get("side") or _position_side(pos) or "").upper()
    market = market_snapshot.snapshot(asset)

    position = {
        "asset":asset,
        "side":side,
        "entry":rec.get("entry") or pos.get("avgPx"),
        "mark_price":pos.get("markPx"),
        "stop_loss":rec.get("stop_loss"),
        "take_profit_1":rec.get("take_profit_1"),
        "take_profit_2":rec.get("take_profit_2"),
    }

    decision = decide_news_exit(position, event, market)
    should_close = (
        decision.get("action") == "CLOSE_NOW"
        and float(decision.get("confidence",0)) >= config.EMERGENCY_NEWS_MIN_CONFIDENCE
    )

    result = {
        "status":"REVIEWED",
        "asset":asset,
        "side":side,
        "age_minutes":age,
        "decision":decision,
        "would_close":should_close,
    }

    if not dry_run:
        seen[key] = {
            "status":"CLOSE" if should_close else "HOLD",
            "at_utc":datetime.now(timezone.utc).isoformat(),
            "decision":decision,
        }
        _save(NEWS_SEEN, seen)

    if should_close and not dry_run:
        result["close"] = _submit_forced_close(
            asset,
            "EMERGENCY_OPPOSITE_VERIFIED_NEWS",
            {
                "event_id":event.get("id"),
                "title":event.get("title"),
                "source":event.get("source"),
                "verification_status":event.get("verification_status"),
                "decision":decision,
            },
        )

    return result

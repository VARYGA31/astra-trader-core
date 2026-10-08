#!/usr/bin/env python3
import json
from datetime import datetime, timezone
from pathlib import Path
import config

STATE_FILE = Path(config.STATE_DIR) / "decision_gate_state.json"

def _load():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save(d):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    t = STATE_FILE.with_suffix(".tmp")
    t.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    t.replace(STATE_FILE)

def score_spot(spot):
    rg = spot.get("regimes", {})
    ind = spot.get("indicators", {})
    ch = spot.get("changes_pct", {})
    book = spot.get("order_book", {})
    flow = spot.get("trade_flow", {})

    score = 0
    reasons = []

    if rg.get("trend") == "BULLISH":
        score += 2; reasons.append("trend_bullish")
    elif rg.get("trend") == "BEARISH":
        score -= 2; reasons.append("trend_bearish")

    if rg.get("momentum") == "BULLISH":
        score += 1; reasons.append("momentum_bullish")
    elif rg.get("momentum") == "BEARISH":
        score -= 1; reasons.append("momentum_bearish")

    # Important change:
    # an EXTREME RSI does NOT add trend-following score.
    # Oversold/overbought is treated as chase-risk instead.
    rsi = ind.get("rsi14")
    if isinstance(rsi, (int, float)):
        if 58 <= rsi < config.LONG_CHASE_RSI:
            score += 1; reasons.append("rsi_positive")
        elif config.SHORT_CHASE_RSI < rsi <= 42:
            score -= 1; reasons.append("rsi_negative")
        elif rsi <= config.SHORT_CHASE_RSI:
            reasons.append("rsi_oversold_no_short_boost")
        elif rsi >= config.LONG_CHASE_RSI:
            reasons.append("rsi_overbought_no_long_boost")

    x = ch.get("1h")
    if isinstance(x, (int, float)):
        if x >= .25:
            score += 1; reasons.append("change_1h_positive")
        elif x <= -.25:
            score -= 1; reasons.append("change_1h_negative")

    x = ch.get("4h")
    if isinstance(x, (int, float)):
        if x >= .60:
            score += 1; reasons.append("change_4h_positive")
        elif x <= -.60:
            score -= 1; reasons.append("change_4h_negative")

    x = book.get("imbalance")
    if isinstance(x, (int, float)):
        if x >= .12:
            score += 1; reasons.append("book_buy_imbalance")
        elif x <= -.12:
            score -= 1; reasons.append("book_sell_imbalance")

    x = flow.get("buy_sell_ratio")
    if isinstance(x, (int, float)):
        if x >= 1.15:
            score += 1; reasons.append("aggressive_buy_flow")
        elif x <= .87:
            score -= 1; reasons.append("aggressive_sell_flow")

    return score, reasons

def _distance_pct(a, b):
    try:
        a = float(a); b = float(b)
        if a <= 0:
            return None
        return abs(a - b) / a * 100.0
    except Exception:
        return None

def chase_guard_from_spot(spot, action):
    """Hard anti-chase guard. Returns blocked=True for late entries."""
    action = str(action or "").upper()
    price = spot.get("price")
    t24 = spot.get("ticker_24h", {})
    ind = spot.get("indicators", {})
    ch = spot.get("changes_pct", {})
    rsi = ind.get("rsi14")
    atr_pct = ind.get("atr_pct")
    one_h = ch.get("1h")

    if not isinstance(price, (int, float)) or not isinstance(rsi, (int, float)):
        return {"blocked": False, "reason": "INSUFFICIENT_CHASE_DATA"}

    low = t24.get("low")
    high = t24.get("high")
    near_low = _distance_pct(price, low)
    near_high = _distance_pct(price, high)

    impulse_limit = None
    if isinstance(atr_pct, (int, float)) and atr_pct > 0:
        impulse_limit = config.CHASE_IMPULSE_ATR_MULT * atr_pct

    if action == "SHORT":
        at_extreme = near_low is not None and near_low <= config.CHASE_EXTREME_DISTANCE_PCT
        impulse = (
            isinstance(one_h, (int, float))
            and impulse_limit is not None
            and one_h <= -impulse_limit
        )
        if rsi <= config.SHORT_CHASE_RSI and (at_extreme or impulse):
            return {
                "blocked": True,
                "reason": "SHORT_CHASE_OVERSOLD",
                "rsi14": rsi,
                "distance_from_24h_low_pct": near_low,
                "change_1h_pct": one_h,
                "atr_pct": atr_pct,
            }

    if action == "LONG":
        at_extreme = near_high is not None and near_high <= config.CHASE_EXTREME_DISTANCE_PCT
        impulse = (
            isinstance(one_h, (int, float))
            and impulse_limit is not None
            and one_h >= impulse_limit
        )
        if rsi >= config.LONG_CHASE_RSI and (at_extreme or impulse):
            return {
                "blocked": True,
                "reason": "LONG_CHASE_OVERBOUGHT",
                "rsi14": rsi,
                "distance_from_24h_high_pct": near_high,
                "change_1h_pct": one_h,
                "atr_pct": atr_pct,
            }

    return {
        "blocked": False,
        "reason": "OK",
        "rsi14": rsi,
        "distance_from_24h_low_pct": near_low,
        "distance_from_24h_high_pct": near_high,
        "change_1h_pct": one_h,
        "atr_pct": atr_pct,
    }

def entry_guard(package, action):
    spot = package.get("decision_context", {}).get("market", {}).get("spot", {})
    return chase_guard_from_spot(spot, action)

def _market_score(package):
    spot = package.get("decision_context", {}).get("market", {}).get("spot", {})
    score, reasons = score_spot(spot)
    return score, reasons, spot.get("last_candle_close_time_ms")

def _verified_event(package):
    for e in package.get("decision_context", {}).get("news", {}).get("events", []):
        if e.get("impact_hint") == "HIGH" and e.get("trade_usable"):
            return e.get("id")
    return None

def evaluate(package, force_event=False):
    g = package.get("guards", {})
    if (
        g.get("market_stale")
        or not g.get("market_ok")
        or not g.get("news_ok")
        or not g.get("critical_news_verified")
        or g.get("trading_halted")
        or g.get("cooldown", {}).get("active")
    ):
        return {"call_model": False, "reason": "GUARD_BLOCK"}

    if int(package.get("account_state", {}).get("open_positions", 0)) >= config.MAX_OPEN_POSITIONS:
        return {"call_model": False, "reason": "MAX_OPEN_POSITIONS"}

    score, reasons, candle = _market_score(package)

    # Save OpenAI credits and prevent late trend-chasing.
    candidate = "LONG" if score >= config.MODEL_GATE_MIN_SCORE else "SHORT" if score <= -config.MODEL_GATE_MIN_SCORE else None
    chase = entry_guard(package, candidate) if candidate else {"blocked": False}
    if chase.get("blocked"):
        return {
            "call_model": False,
            "reason": chase["reason"],
            "score": score,
            "score_reasons": reasons,
            "chase_guard": chase,
        }

    ev = _verified_event(package)
    st = _load()
    old = st.get(package.get("asset", ""), {})
    new_candle = candle is not None and candle != old.get("last_candle_close_time_ms")
    new_event = ev is not None and ev != old.get("last_verified_event_id")

    call = bool(
        (new_candle and abs(score) >= config.MODEL_GATE_MIN_SCORE)
        or new_event
        or (force_event and ev)
    )
    reason = "MODEL_GATE_PASS" if call else (
        "SAME_CANDLE" if not new_candle and not new_event else "NO_STRONG_SETUP"
    )

    if call:
        st[package.get("asset", "")] = {
            "last_candle_close_time_ms": candle,
            "last_verified_event_id": ev,
            "last_gate_score": score,
            "last_called_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        _save(st)

    return {
        "call_model": call,
        "reason": reason,
        "score": score,
        "score_reasons": reasons,
        "new_candle": new_candle,
        "new_verified_high_event": new_event,
        "chase_guard": chase,
    }

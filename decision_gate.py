#!/usr/bin/env python3
import json
from datetime import datetime, timezone
from pathlib import Path
import config
from okx_demo_adapter import OKXDemoAdapter

STATE_FILE = Path(config.STATE_DIR) / "decision_gate_state.json"

DEFI_SECURITY_WORDS=(
    "exploit","exploited","hack","hacked","drain","drained","vulnerability",
    "oracle attack","oracle failure","depeg","de-peg","compromised",
    "emergency pause","security incident","stolen funds"
)

def _defi_account_tradability_guard(package):
    asset=str((package or {}).get("asset") or "").upper()
    if asset not in set(config.DEFI_TRADE_WATCHLIST):
        return None
    if str((package or {}).get("execution_mode") or config.EXECUTION_MODE).lower() != "okx_demo":
        return None
    try:
        tradability=OKXDemoAdapter().account_tradability(asset)
    except Exception as e:
        return {
            "call_model":False,
            "reason":"DEFI_ACCOUNT_TRADABILITY_CHECK_FAILED",
            "tradability":{
                "available":False,
                "reason":"UNCAUGHT_ACCOUNT_TRADABILITY_ERROR",
                "instrument":asset,
                "error_type":type(e).__name__,
                "error":str(e)[:500],
            },
        }
    if tradability.get("available"):
        return None
    reason=(
        "DEFI_ACCOUNT_INSTRUMENT_UNAVAILABLE"
        if tradability.get("reason")=="ACCOUNT_INSTRUMENT_UNAVAILABLE"
        else "DEFI_ACCOUNT_TRADABILITY_CHECK_FAILED"
    )
    return {
        "call_model":False,
        "reason":reason,
        "tradability":tradability,
    }

def _defi_pretrade_guard(package):
    asset=str((package or {}).get("asset") or "").upper()
    if asset not in set(config.DEFI_TRADE_WATCHLIST):
        return None

    perp=((package or {}).get("decision_context") or {}).get("market",{}).get("perp_okx",{})
    try:
        bid=float(perp.get("bid_price")); ask=float(perp.get("ask_price"))
        mid=(bid+ask)/2.0
        spread=((ask-bid)/mid*100.0) if mid>0 and ask>=bid else None
    except Exception:
        spread=None
    if spread is None:
        return {"call_model":False,"reason":"DEFI_SPREAD_UNAVAILABLE"}
    if spread>float(config.DEFI_TRADE_MAX_SPREAD_PCT):
        return {
            "call_model":False,"reason":"DEFI_SPREAD_TOO_WIDE",
            "spread_pct":spread,"maximum_pct":float(config.DEFI_TRADE_MAX_SPREAD_PCT),
        }

    now_dt=datetime.now(timezone.utc)
    for e in ((package or {}).get("decision_context") or {}).get("news",{}).get("events",[]):
        text=(" ".join(str(e.get(k) or "") for k in ("title","summary","event_type"))).lower()
        if not any(w in text for w in DEFI_SECURITY_WORDS):
            continue
        dt=_parse_event_time(e.get("published_at_utc"))
        if dt is None or (now_dt-dt).total_seconds()<=float(config.DEFI_SECURITY_HALT_HOURS)*3600.0:
            return {
                "call_model":False,"reason":"DEFI_SECURITY_HALT",
                "event":{k:e.get(k) for k in ("id","source","title","published_at_utc")},
            }
    return None

def _parse_event_time(x):
    try:return datetime.fromisoformat(str(x or "").replace("Z","+00:00"))
    except Exception:return None

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

def _verified_event(package):
    for e in package.get("decision_context", {}).get("news", {}).get("events", []):
        if e.get("impact_hint")=="HIGH" and e.get("trade_usable"):
            return e.get("id")
    return None

def _new_verified_high_event_obj(package):
    events=package.get("decision_context",{}).get("news",{}).get("events",[])
    for e in events:
        if e.get("impact_hint")=="HIGH" and e.get("trade_usable"):
            return e
    return None

def _event_age_minutes(e):
    if not e:return None
    try:
        dt=datetime.fromisoformat((e.get("published_at_utc") or "").replace("Z","+00:00"))
        return (datetime.now(timezone.utc)-dt).total_seconds()/60.0
    except Exception:
        return None

def evaluate(package, force_event=False):
    import mtf_gate

    g=package.get("guards",{})
    if (
        g.get("market_stale")
        or not g.get("market_ok")
        or not g.get("news_ok")
        or not g.get("critical_news_verified")
        or g.get("trading_halted")
        or g.get("cooldown",{}).get("active")
        or g.get("loss_streak_pause",{}).get("active")
        or (package.get("asset")=="XAU" and not g.get("xau_session_ok",False))
        or (package.get("asset")=="XAU" and not g.get("gold_macro_ok",False))
        or (package.get("asset")=="XAU" and not g.get("gold_macro_primary_ok",False))
    ):
        return {"call_model":False,"reason":"GUARD_BLOCK","guards":g}

    defi_guard=_defi_pretrade_guard(package)
    if defi_guard:
        return defi_guard

    if int(package.get("account_state",{}).get("open_positions",0))>=config.MAX_OPEN_POSITIONS:
        return {"call_model":False,"reason":"MAX_OPEN_POSITIONS"}

    mtf=mtf_gate.evaluate(package)
    if not mtf.get("passed"):
        return {
            "call_model":False,
            "reason":mtf.get("reason","MTF_NOT_ALIGNED"),
            "mtf":mtf,
        }
    if (
        str(package.get("asset") or "").upper() in set(config.DEFI_TRADE_WATCHLIST)
        and str(mtf.get("mode") or "").upper()=="TRANSITION"
    ):
        return {"call_model":False,"reason":"DEFI_TRANSITION_NOT_ALLOWED","mtf":mtf}

    # Only spend a model call on DeFi when the authenticated demo account can
    # actually see the swap. This is deliberately after MTF so ordinary rejected
    # setups do not create extra private API traffic.
    defi_account_guard=_defi_account_tradability_guard(package)
    if defi_account_guard:
        defi_account_guard["mtf"]=mtf
        return defi_account_guard

    # For gold, do not enter in the first few minutes after a fresh verified
    # high-impact macro headline. Wait for price discovery / 15m confirmation.
    if package.get("asset")=="XAU":
        ev_obj=_new_verified_high_event_obj(package)
        age=_event_age_minutes(ev_obj)
        if age is not None and age < config.XAU_NEWS_SETTLE_MINUTES:
            return {
                "call_model":False,
                "reason":"XAU_MACRO_NEWS_SETTLE",
                "news_age_minutes":age,
                "settle_minutes":config.XAU_NEWS_SETTLE_MINUTES,
                "event":{k:ev_obj.get(k) for k in ("id","source","title","event_type","impact_hint")},
                "mtf":mtf,
            }

    # Existing anti-chase guard remains as another layer.
    chase=entry_guard(package,mtf.get("direction"))
    if chase.get("blocked"):
        return {
            "call_model":False,
            "reason":chase.get("reason"),
            "mtf":mtf,
            "chase_guard":chase,
        }

    ev=_verified_event(package)
    st=_load()
    asset=package.get("asset","")
    old=st.get(asset,{})
    candle=mtf.get("trigger_candle_id")
    new_trigger=candle is not None and candle!=old.get("last_trigger_candle_id")
    new_event=ev is not None and ev!=old.get("last_verified_event_id")

    call=bool(new_trigger or (force_event and new_event))
    reason="MODEL_GATE_PASS" if call else "SAME_15M_TRIGGER"

    if call:
        st[asset]={
            "last_trigger_candle_id":candle,
            "last_verified_event_id":ev,
            "last_mtf_direction":mtf.get("direction"),
            "last_mtf_quality":mtf.get("quality"),
            "last_mtf_mode":mtf.get("mode"),
            "last_called_at_utc":datetime.now(timezone.utc).isoformat(),
        }
        _save(st)

    return {
        "call_model":call,
        "reason":reason,
        "allowed_direction":mtf.get("direction"),
        "mtf_quality":mtf.get("quality"),
        "mtf_mode":mtf.get("mode"),
        "new_trigger_candle":new_trigger,
        "new_verified_high_event":new_event,
        "mtf":mtf,
        "chase_guard":chase,
    }

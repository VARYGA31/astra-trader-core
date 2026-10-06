#!/usr/bin/env python3
import sys, json
from dataclasses import dataclass

ALLOWED_ASSETS = {"BTC", "ETH", "GRAM"}

@dataclass
class RiskConfig:
    initial_equity: float = 100.0
    normal_position_pct: float = 0.10
    max_position_pct: float = 0.20

    normal_risk_pct: float = 0.02
    hard_risk_pct: float = 0.03

    daily_loss_limit_pct: float = 0.06
    max_drawdown_pct: float = 0.25

    max_total_exposure_pct: float = 0.30
    max_open_positions: int = 2

    default_leverage: float = 3.0
    max_leverage: float = 5.0

    margin_mode: str = "ISOLATED"
    stop_loss_required: bool = True
    martingale_allowed: bool = False
    average_down_allowed: bool = False
    auto_restart: bool = False


CFG = RiskConfig()

def reject(reason, extra=None):
    out = {
        "status": "REJECTED",
        "reason": reason,
        "config": CFG.__dict__,
    }
    if extra:
        out.update(extra)
    return out

def approve(payload):
    return {
        "status": "APPROVED",
        **payload,
        "config": CFG.__dict__,
    }

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

def drawdown_pct(initial_equity, equity):
    if initial_equity <= 0:
        return 1.0
    return max(0.0, (initial_equity - equity) / initial_equity)

def risk_multiplier_by_drawdown(dd):
    if dd >= 0.25:
        return 0.0, "HARD_STOP"
    if dd >= 0.20:
        return 0.25, "SURVIVAL"
    if dd >= 0.15:
        return 0.50, "DEFENSIVE"
    if dd >= 0.10:
        return 0.75, "CAUTIOUS"
    return 1.0, "NORMAL"

def choose_leverage(requested, confidence, volatility_regime):
    # Default 3x. 5x allowed only under stronger conditions.
    lev = requested if requested is not None else CFG.default_leverage
    lev = clamp(float(lev), 1.0, CFG.max_leverage)

    if volatility_regime in {"HIGH", "EXTREME"}:
        return min(lev, 3.0), "CAPPED_DUE_TO_VOLATILITY"

    if lev > 3.0 and confidence < 75:
        return 3.0, "CAPPED_DUE_TO_CONFIDENCE"

    return lev, "OK"

def evaluate(data):
    asset = str(data.get("asset", "")).upper()
    action = str(data.get("action", "")).upper()
    equity = float(data.get("equity", CFG.initial_equity))
    initial_equity = float(data.get("initial_equity", CFG.initial_equity))
    daily_pnl = float(data.get("daily_pnl", 0.0))
    open_positions = int(data.get("open_positions", 0))
    current_exposure_usd = float(data.get("current_exposure_usd", 0.0))

    entry = data.get("entry")
    stop = data.get("stop_loss")
    confidence = float(data.get("confidence", 0))
    data_quality = str(data.get("data_quality", "FAILED")).upper()
    high_impact_verified = bool(data.get("high_impact_news_verified", True))
    volatility_regime = str(data.get("volatility_regime", "NORMAL")).upper()
    requested_leverage = data.get("leverage")

    if asset not in ALLOWED_ASSETS:
        return reject("TRADE_NOT_ALLOWED", {"allowed_assets": sorted(ALLOWED_ASSETS)})

    if action not in {"LONG", "SHORT"}:
        return reject("NO_ACTION_TO_EXECUTE")

    if data_quality == "FAILED":
        return reject("MARKET_DATA_FAILED")

    if not high_impact_verified:
        return reject("UNVERIFIED_HIGH_IMPACT_NEWS")

    if CFG.stop_loss_required and stop is None:
        return reject("STOP_LOSS_REQUIRED")

    if entry is None:
        return reject("ENTRY_REQUIRED")

    entry = float(entry)
    stop = float(stop)

    if entry <= 0 or stop <= 0:
        return reject("INVALID_PRICE")

    if action == "LONG" and stop >= entry:
        return reject("INVALID_STOP_FOR_LONG")

    if action == "SHORT" and stop <= entry:
        return reject("INVALID_STOP_FOR_SHORT")

    dd = drawdown_pct(initial_equity, equity)
    risk_mult, mode = risk_multiplier_by_drawdown(dd)

    if mode == "HARD_STOP":
        return reject("MAX_DRAWDOWN_REACHED", {
            "drawdown_pct": dd,
            "trading_halted": True,
            "auto_restart": False,
        })

    if daily_pnl <= -(equity * CFG.daily_loss_limit_pct):
        return reject("DAILY_LOSS_LIMIT_REACHED", {
            "daily_pnl": daily_pnl,
            "daily_loss_limit_usd": equity * CFG.daily_loss_limit_pct,
        })

    if open_positions >= CFG.max_open_positions:
        return reject("MAX_OPEN_POSITIONS_REACHED")

    stop_distance_pct = abs(entry - stop) / entry
    if stop_distance_pct <= 0:
        return reject("ZERO_STOP_DISTANCE")

    allowed_risk_pct = CFG.normal_risk_pct * risk_mult
    allowed_risk_pct = min(allowed_risk_pct, CFG.hard_risk_pct)
    allowed_risk_usd = equity * allowed_risk_pct

    leverage, leverage_note = choose_leverage(
        requested_leverage,
        confidence,
        volatility_regime
    )

    # Position sizing:
    # loss at stop = notional_position * stop_distance_pct
    risk_based_notional = allowed_risk_usd / stop_distance_pct

    normal_notional = equity * CFG.normal_position_pct
    max_notional = equity * CFG.max_position_pct

    # Start with a 10% position target, allow expansion up to 20% only if risk permits.
    target_notional = min(max(normal_notional, risk_based_notional), max_notional)

    # Ensure actual risk at stop never exceeds allowed risk.
    if target_notional * stop_distance_pct > allowed_risk_usd:
        target_notional = allowed_risk_usd / stop_distance_pct

    # Total account exposure cap.
    remaining_exposure = max(0.0, equity * CFG.max_total_exposure_pct - current_exposure_usd)
    target_notional = min(target_notional, remaining_exposure)

    if target_notional <= 0:
        return reject("NO_EXPOSURE_CAPACITY")

    actual_risk_usd = target_notional * stop_distance_pct
    actual_risk_pct = actual_risk_usd / equity if equity > 0 else 1.0

    if actual_risk_pct > CFG.hard_risk_pct + 1e-12:
        return reject("HARD_RISK_LIMIT_EXCEEDED")

    margin_required = target_notional / leverage

    return approve({
        "asset": asset,
        "action": action,
        "risk_mode": mode,
        "equity": equity,
        "drawdown_pct": dd,
        "entry": entry,
        "stop_loss": stop,
        "stop_distance_pct": stop_distance_pct,
        "allowed_risk_pct": allowed_risk_pct,
        "allowed_risk_usd": allowed_risk_usd,
        "position_notional_usd": target_notional,
        "position_pct_of_equity": target_notional / equity if equity else None,
        "actual_risk_usd": actual_risk_usd,
        "actual_risk_pct": actual_risk_pct,
        "leverage": leverage,
        "leverage_note": leverage_note,
        "margin_required_usd": margin_required,
        "margin_mode": CFG.margin_mode,
        "current_exposure_usd": current_exposure_usd,
        "remaining_exposure_after_trade_usd": max(
            0.0,
            equity * CFG.max_total_exposure_pct - current_exposure_usd - target_notional
        ),
        "trading_halted": False,
        "auto_restart": CFG.auto_restart,
    })

def main():
    if len(sys.argv) > 1:
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)

    result = evaluate(data)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))

if __name__ == "__main__":
    main()

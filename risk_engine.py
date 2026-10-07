#!/usr/bin/env python3
import sys, json, config

ALLOWED = set(config.ALLOWED_ASSETS)

def reject(reason, extra=None):
    x = {"status":"REJECTED","reason":reason}
    if extra:
        x.update(extra)
    return x

def _rr(entry, stop, target):
    risk = abs(entry - stop)
    if risk <= 0:
        return 0.0
    return abs(float(target) - entry) / risk

def evaluate(d):
    asset = str(d.get("asset","")).upper()
    action = str(d.get("action","")).upper()
    eq = float(d.get("equity", config.INITIAL_EQUITY))
    init = float(d.get("initial_equity", config.INITIAL_EQUITY))

    if asset not in ALLOWED:
        return reject("TRADE_NOT_ALLOWED")
    if action not in {"LONG","SHORT"}:
        return reject("NO_ACTION_TO_EXECUTE")
    if str(d.get("data_quality","FAILED")).upper() == "FAILED":
        return reject("MARKET_DATA_FAILED")
    if not bool(d.get("critical_news_verified", False)):
        return reject("UNVERIFIED_HIGH_IMPACT_NEWS")
    if d.get("entry") is None:
        return reject("ENTRY_REQUIRED")
    if d.get("stop_loss") is None:
        return reject("STOP_LOSS_REQUIRED")
    if d.get("take_profit_1") is None or d.get("take_profit_2") is None:
        return reject("TAKE_PROFITS_REQUIRED")

    entry = float(d["entry"])
    stop = float(d["stop_loss"])
    tp1 = float(d["take_profit_1"])
    tp2 = float(d["take_profit_2"])

    if min(entry, stop, tp1, tp2) <= 0:
        return reject("INVALID_PRICE")

    if action == "LONG":
        if not (stop < entry < tp1 < tp2):
            return reject("INVALID_LEVELS_FOR_LONG", {
                "entry":entry, "stop_loss":stop, "tp1":tp1, "tp2":tp2
            })
    else:
        if not (stop > entry > tp1 > tp2):
            return reject("INVALID_LEVELS_FOR_SHORT", {
                "entry":entry, "stop_loss":stop, "tp1":tp1, "tp2":tp2
            })

    rr1 = _rr(entry, stop, tp1)
    rr2 = _rr(entry, stop, tp2)
    if rr1 < config.MIN_TP1_R:
        return reject("TP1_REWARD_RISK_TOO_LOW", {"tp1_r":rr1, "minimum":config.MIN_TP1_R})
    if rr2 < config.MIN_TP2_R:
        return reject("TP2_REWARD_RISK_TOO_LOW", {"tp2_r":rr2, "minimum":config.MIN_TP2_R})

    if config.ONE_POSITION_PER_ASSET and bool(d.get("asset_already_open", False)):
        return reject("ASSET_ALREADY_HAS_OPEN_POSITION")

    dd = max(0.0, (init - eq) / init) if init > 0 else 1.0
    if dd >= config.MAX_DRAWDOWN_PCT:
        return reject("MAX_DRAWDOWN_REACHED", {"trading_halted":True})
    if float(d.get("daily_pnl",0)) <= -(init * config.DAILY_LOSS_LIMIT_PCT):
        return reject("DAILY_LOSS_LIMIT_REACHED")
    if int(d.get("open_positions",0)) >= config.MAX_OPEN_POSITIONS:
        return reject("MAX_OPEN_POSITIONS_REACHED")

    mult = .25 if dd >= .20 else .5 if dd >= .15 else .75 if dd >= .10 else 1.0
    stop_dist_pct = abs(entry - stop) / entry
    if stop_dist_pct <= 0:
        return reject("INVALID_STOP_DISTANCE")

    risk_pct = min(config.NORMAL_RISK_PCT * mult, config.HARD_RISK_PCT)
    risk_usd = eq * risk_pct

    leverage = min(max(float(d.get("leverage", config.DEFAULT_LEVERAGE)),1), config.MAX_LEVERAGE)
    if str(d.get("volatility_regime","NORMAL")).upper() in {"HIGH","EXTREME"} or (
        leverage > 3 and float(d.get("confidence",0)) < 75
    ):
        leverage = 3

    notional = min(
        max(eq * config.NORMAL_POSITION_PCT, risk_usd / stop_dist_pct),
        eq * config.MAX_POSITION_PCT
    )
    if notional * stop_dist_pct > risk_usd:
        notional = risk_usd / stop_dist_pct

    exposure_left = max(
        0.0,
        eq * config.MAX_TOTAL_EXPOSURE_PCT - float(d.get("current_exposure_usd",0))
    )
    notional = min(notional, exposure_left)
    if notional <= 0:
        return reject("NO_EXPOSURE_CAPACITY")

    return {
        "status":"APPROVED",
        "asset":asset,
        "action":action,
        "entry":entry,
        "stop_loss":stop,
        "take_profit_1":tp1,
        "take_profit_2":tp2,
        "tp1_r":rr1,
        "tp2_r":rr2,
        "position_notional_usd":notional,
        "actual_risk_usd":notional * stop_dist_pct,
        "actual_risk_pct":(notional * stop_dist_pct / eq) if eq > 0 else 0,
        "leverage":leverage,
        "margin_required_usd":notional / leverage,
    }

if __name__=="__main__":
    d = json.load(open(sys.argv[1],encoding="utf-8")) if len(sys.argv)>1 else json.load(sys.stdin)
    print(json.dumps(evaluate(d),ensure_ascii=False,separators=(",",":")))

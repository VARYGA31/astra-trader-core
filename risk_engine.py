#!/usr/bin/env python3
import sys,json,config

ALLOWED=set(config.ALLOWED_ASSETS)

def reject(reason,extra=None):
    x={"status":"REJECTED","reason":reason}
    if extra:x.update(extra)
    return x

def _rr(entry,stop,target):
    risk=abs(entry-stop)
    return abs(float(target)-entry)/risk if risk>0 else 0.0

def _risk_pct(confidence,mtf_quality,dd_mult):
    quality=min(float(confidence),float(mtf_quality))
    if quality < config.MIN_TRADE_CONFIDENCE:
        return None,quality
    if quality < 85:
        base=config.RISK_PCT_80_84
    elif quality < 92:
        base=config.RISK_PCT_85_91
    else:
        base=config.RISK_PCT_92_PLUS
    return min(base*dd_mult,config.HARD_RISK_PCT),quality

def _leverage(volatility,quality,stop_dist_pct):
    v=str(volatility or "NORMAL").upper()
    if v in {"ELEVATED","HIGH","EXTREME"}:
        lev=config.LEVERAGE_HIGH_VOL
    elif (
        quality>=config.BEST_SETUP_MIN_QUALITY
        and stop_dist_pct*100<=config.BEST_SETUP_MAX_STOP_PCT
    ):
        lev=config.LEVERAGE_BEST_SETUP
    else:
        lev=config.LEVERAGE_NORMAL
    return min(max(float(lev),1.0),float(config.MAX_LEVERAGE))

def evaluate(d):
    asset=str(d.get("asset","")).upper()
    action=str(d.get("action","")).upper()
    eq=float(d.get("equity",config.INITIAL_EQUITY))
    init=float(d.get("initial_equity",config.INITIAL_EQUITY))

    if asset not in ALLOWED:return reject("TRADE_NOT_ALLOWED")
    if action not in {"LONG","SHORT"}:return reject("NO_ACTION_TO_EXECUTE")
    if str(d.get("data_quality","FAILED")).upper()=="FAILED":return reject("MARKET_DATA_FAILED")
    if not bool(d.get("critical_news_verified",False)):return reject("UNVERIFIED_HIGH_IMPACT_NEWS")
    if d.get("entry") is None:return reject("ENTRY_REQUIRED")
    if d.get("stop_loss") is None:return reject("STOP_LOSS_REQUIRED")
    if d.get("take_profit_1") is None or d.get("take_profit_2") is None:return reject("TAKE_PROFITS_REQUIRED")

    confidence=float(d.get("confidence",0) or 0)
    mtf_quality=float(d.get("mtf_quality",0) or 0)
    if confidence<config.MIN_TRADE_CONFIDENCE:
        return reject("CONFIDENCE_TOO_LOW",{"confidence":confidence,"minimum":config.MIN_TRADE_CONFIDENCE})
    if mtf_quality<config.MTF_MIN_QUALITY:
        return reject("MTF_QUALITY_TOO_LOW",{"mtf_quality":mtf_quality,"minimum":config.MTF_MIN_QUALITY})

    entry=float(d["entry"]); stop=float(d["stop_loss"])
    tp1=float(d["take_profit_1"]); tp2=float(d["take_profit_2"])
    if min(entry,stop,tp1,tp2)<=0:return reject("INVALID_PRICE")

    if action=="LONG":
        if not (stop<entry<tp1<tp2):
            return reject("INVALID_LEVELS_FOR_LONG")
    else:
        if not (stop>entry>tp1>tp2):
            return reject("INVALID_LEVELS_FOR_SHORT")

    rr1=_rr(entry,stop,tp1); rr2=_rr(entry,stop,tp2)
    if rr1<config.MIN_TP1_R:
        return reject("TP1_REWARD_RISK_TOO_LOW",{"tp1_r":rr1,"minimum":config.MIN_TP1_R})
    if rr2<config.MIN_TP2_R:
        return reject("TP2_REWARD_RISK_TOO_LOW",{"tp2_r":rr2,"minimum":config.MIN_TP2_R})

    if config.ONE_POSITION_PER_ASSET and bool(d.get("asset_already_open",False)):
        return reject("ASSET_ALREADY_HAS_OPEN_POSITION")

    dd=max(0.0,(init-eq)/init) if init>0 else 1.0
    if dd>=config.MAX_DRAWDOWN_PCT:
        return reject("MAX_DRAWDOWN_REACHED",{"trading_halted":True})
    if float(d.get("daily_pnl",0))<=-(init*config.DAILY_LOSS_LIMIT_PCT):
        return reject("DAILY_LOSS_LIMIT_REACHED")
    if int(d.get("open_positions",0))>=config.MAX_OPEN_POSITIONS:
        return reject("MAX_OPEN_POSITIONS_REACHED")

    dd_mult=.25 if dd>=.20 else .5 if dd>=.15 else .75 if dd>=.10 else 1.0
    stop_dist_pct=abs(entry-stop)/entry
    if stop_dist_pct<=0:return reject("INVALID_STOP_DISTANCE")

    risk_pct,quality=_risk_pct(confidence,mtf_quality,dd_mult)
    if risk_pct is None:
        return reject("TRADE_QUALITY_TOO_LOW",{"quality":quality})

    risk_usd=eq*risk_pct
    leverage=_leverage(d.get("volatility_regime"),quality,stop_dist_pct)

    # Notional is always risk-budgeted. Higher leverage does NOT increase risk budget.
    notional=min(
        max(eq*config.NORMAL_POSITION_PCT,risk_usd/stop_dist_pct),
        eq*config.MAX_POSITION_PCT
    )
    if notional*stop_dist_pct>risk_usd:
        notional=risk_usd/stop_dist_pct

    exposure_left=max(0.0,eq*config.MAX_TOTAL_EXPOSURE_PCT-float(d.get("current_exposure_usd",0)))
    notional=min(notional,exposure_left)
    if notional<=0:return reject("NO_EXPOSURE_CAPACITY")

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
        "confidence":confidence,
        "mtf_quality":mtf_quality,
        "trade_quality":quality,
        "risk_pct_budget":risk_pct,
        "position_notional_usd":notional,
        "actual_risk_usd":notional*stop_dist_pct,
        "actual_risk_pct":(notional*stop_dist_pct/eq) if eq>0 else 0,
        "leverage":leverage,
        "margin_required_usd":notional/leverage,
    }

if __name__=="__main__":
    d=json.load(open(sys.argv[1],encoding="utf-8")) if len(sys.argv)>1 else json.load(sys.stdin)
    print(json.dumps(evaluate(d),ensure_ascii=False,separators=(",",":")))

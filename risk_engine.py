#!/usr/bin/env python3
import sys,json,config

ALLOWED=set(config.ALLOWED_ASSETS)
DEFI=set(config.DEFI_TRADE_WATCHLIST)

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

def _scalp_risk_pct(confidence,mtf_quality,dd_mult):
    quality=min(float(confidence),float(mtf_quality))
    if quality < config.SCALP_MIN_TRADE_CONFIDENCE:
        return None,quality
    if quality < 87:
        base=config.SCALP_RISK_PCT_82_86
    elif quality < 92:
        base=config.SCALP_RISK_PCT_87_91
    else:
        base=config.SCALP_RISK_PCT_92_PLUS
    return min(base*dd_mult,config.SCALP_HARD_RISK_PCT),quality

def _scalp_fast_risk_pct(confidence,mtf_quality,dd_mult):
    confidence=float(confidence); mtf_quality=float(mtf_quality)
    quality=min(confidence,mtf_quality)
    if confidence < config.SCALP_FAST_MIN_TRADE_CONFIDENCE or mtf_quality < config.SCALP_FAST_MIN_QUALITY:
        return None,quality
    best=(confidence>=config.SCALP_FAST_BEST_MIN_CONFIDENCE and mtf_quality>=config.SCALP_FAST_BEST_MIN_QUALITY)
    base=config.SCALP_FAST_RISK_PCT_BEST if best else config.SCALP_FAST_RISK_PCT_BASE
    return min(base*dd_mult,config.SCALP_FAST_HARD_RISK_PCT),quality

def _micro_risk_pct(confidence,mtf_quality,dd_mult):
    confidence=float(confidence); mtf_quality=float(mtf_quality)
    quality=min(confidence,mtf_quality)
    if confidence<config.MICRO_MIN_TRADE_CONFIDENCE or mtf_quality<config.MICRO_MIN_QUALITY:
        return None,quality
    best=(confidence>=config.MICRO_BEST_MIN_CONFIDENCE and mtf_quality>=config.MICRO_BEST_MIN_QUALITY)
    base=config.MICRO_RISK_PCT_BEST if best else config.MICRO_RISK_PCT_BASE
    return min(base*dd_mult,config.MICRO_HARD_RISK_PCT),quality

def _leverage(asset, volatility, quality, confidence, stop_dist_pct, strategy_mode="NORMAL", scalp_tier="PRIME"):
    v=str(volatility or "NORMAL").upper()
    strategy_mode=str(strategy_mode or "NORMAL").upper()

    if strategy_mode=="MICRO":
        if v in {"ELEVATED","HIGH","EXTREME"}:
            lev=config.MICRO_LEVERAGE_HIGH_VOL
        elif quality>=config.MICRO_BEST_MIN_QUALITY and confidence>=config.MICRO_BEST_MIN_CONFIDENCE:
            lev=config.MICRO_LEVERAGE_BEST_SETUP
        else:
            lev=config.MICRO_LEVERAGE_NORMAL
        return min(max(float(lev),1.0),float(config.MICRO_MAX_LEVERAGE))

    if strategy_mode=="SCALP":
        scalp_tier=str(scalp_tier or "PRIME").upper()
        if scalp_tier=="FAST":
            lev=config.SCALP_FAST_LEVERAGE_HIGH_VOL if v in {"ELEVATED","HIGH","EXTREME"} else config.SCALP_FAST_LEVERAGE_NORMAL
            return min(max(float(lev),1.0),float(config.SCALP_FAST_MAX_LEVERAGE))
        if v in {"ELEVATED","HIGH","EXTREME"}:
            lev=config.SCALP_LEVERAGE_HIGH_VOL
        elif quality>=config.SCALP_BEST_SETUP_MIN_QUALITY and confidence>=config.SCALP_BEST_SETUP_MIN_CONFIDENCE:
            lev=config.SCALP_LEVERAGE_BEST_SETUP
        else:
            lev=config.SCALP_LEVERAGE_NORMAL
        return min(max(float(lev),1.0),float(config.SCALP_MAX_LEVERAGE))

    if asset in DEFI:
        # DeFi is allowed only with conservative margin leverage.
        if v in {"ELEVATED","HIGH","EXTREME"}:
            lev=min(float(config.LEVERAGE_HIGH_VOL),float(config.DEFI_TRADE_MAX_LEVERAGE))
        else:
            lev=min(float(config.LEVERAGE_NORMAL),float(config.DEFI_TRADE_MAX_LEVERAGE))
        return max(1.0,float(lev))

    if asset=="XAU":
        # User-requested 5x..10x range for gold only.
        # Higher leverage does NOT enlarge the stop-risk budget.
        if v in {"ELEVATED","HIGH","EXTREME"}:
            lev=config.XAU_MIN_LEVERAGE
        elif (
            quality>=config.XAU_BEST_SETUP_MIN_QUALITY
            and confidence>=config.XAU_BEST_SETUP_MIN_CONFIDENCE
            and stop_dist_pct*100<=config.XAU_BEST_SETUP_MAX_STOP_PCT
        ):
            lev=config.XAU_MAX_LEVERAGE
        else:
            lev=config.XAU_NORMAL_LEVERAGE
        return min(max(float(lev),config.XAU_MIN_LEVERAGE),config.XAU_MAX_LEVERAGE)

    if v in {"ELEVATED","HIGH","EXTREME"}:
        lev=config.LEVERAGE_HIGH_VOL
    elif (
        quality>=config.BEST_SETUP_MIN_QUALITY
        and confidence>=config.BEST_SETUP_MIN_CONFIDENCE
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
    if asset in config.DISABLED_ENTRY_ASSETS:return reject("ASSET_NEW_ENTRIES_DISABLED")
    if not config.MICRO_NEW_ENTRIES_ENABLED and (
        str(d.get("strategy_mode") or "").upper()=="MICRO"
        or str(d.get("mtf_mode") or "").upper()=="MICRO"
    ):return reject("MICRO_DISABLED")
    if action not in {"LONG","SHORT"}:return reject("NO_ACTION_TO_EXECUTE")
    if str(d.get("data_quality","FAILED")).upper()=="FAILED":return reject("MARKET_DATA_FAILED")
    if not bool(d.get("critical_news_verified",False)):return reject("UNVERIFIED_HIGH_IMPACT_NEWS")
    if d.get("entry") is None:return reject("ENTRY_REQUIRED")
    if d.get("stop_loss") is None:return reject("STOP_LOSS_REQUIRED")
    if d.get("take_profit_1") is None or d.get("take_profit_2") is None:return reject("TAKE_PROFITS_REQUIRED")

    confidence=float(d.get("confidence",0) or 0)
    mtf_quality=float(d.get("mtf_quality",0) or 0)
    mtf_mode=str(d.get("mtf_mode") or d.get("mtf_gate",{}).get("mode") or "NORMAL").upper()
    strategy_mode=str(d.get("strategy_mode") or ("MICRO" if mtf_mode=="MICRO" else "SCALP" if mtf_mode=="SCALP" else "NORMAL")).upper()
    is_micro=(strategy_mode=="MICRO" or mtf_mode=="MICRO")
    is_scalp=(strategy_mode=="SCALP" or mtf_mode=="SCALP")
    scalp_tier=str(d.get("scalp_tier") or d.get("gate",{}).get("scalp_tier") or d.get("mtf_gate",{}).get("tier") or "PRIME").upper()
    if scalp_tier not in {"PRIME","FAST"}: scalp_tier="PRIME"
    is_transition=(mtf_mode=="TRANSITION")

    if is_micro:
        if asset not in set(config.MICRO_ALLOWED_ASSETS):
            return reject("MICRO_ASSET_NOT_ALLOWED")
        if confidence<config.MICRO_MIN_TRADE_CONFIDENCE:
            return reject("MICRO_CONFIDENCE_TOO_LOW",{"confidence":confidence,"minimum":config.MICRO_MIN_TRADE_CONFIDENCE})
        if mtf_quality<config.MICRO_MIN_QUALITY:
            return reject("MICRO_QUALITY_TOO_LOW",{"mtf_quality":mtf_quality,"minimum":config.MICRO_MIN_QUALITY})
    elif is_scalp:
        if asset not in set(config.SCALP_ALLOWED_ASSETS):
            return reject("SCALP_ASSET_NOT_ALLOWED")
        min_conf=config.SCALP_FAST_MIN_TRADE_CONFIDENCE if scalp_tier=="FAST" else config.SCALP_MIN_TRADE_CONFIDENCE
        min_quality=(
            config.SCALP_FAST_MIN_QUALITY
            if scalp_tier=="FAST"
            else max(config.SCALP_MIN_QUALITY,config.SCALP_MIN_TRADE_CONFIDENCE)
        )
        if confidence<min_conf:
            return reject("SCALP_CONFIDENCE_TOO_LOW",{"confidence":confidence,"minimum":min_conf,"scalp_tier":scalp_tier})
        if mtf_quality<min_quality:
            return reject("SCALP_QUALITY_TOO_LOW",{"mtf_quality":mtf_quality,"minimum":min_quality,"scalp_tier":scalp_tier})
    elif is_transition:
        # Transition mode is kept away from XAU and DeFi. Extended markets
        # require the full NORMAL alignment until they build their own evidence.
        if asset=="XAU":
            return reject("XAU_TRANSITION_NOT_ALLOWED")
        if asset in DEFI:
            return reject("DEFI_TRANSITION_NOT_ALLOWED")
        if confidence<config.MTF_TRANSITION_MIN_CONFIDENCE:
            return reject("TRANSITION_CONFIDENCE_TOO_LOW",{
                "confidence":confidence,
                "minimum":config.MTF_TRANSITION_MIN_CONFIDENCE,
            })
        if mtf_quality<config.MTF_TRANSITION_MIN_QUALITY:
            return reject("TRANSITION_MTF_QUALITY_TOO_LOW",{
                "mtf_quality":mtf_quality,
                "minimum":config.MTF_TRANSITION_MIN_QUALITY,
            })
    else:
        if asset=="XAU":
            min_conf=config.XAU_MIN_TRADE_CONFIDENCE
            min_mtf=config.XAU_MTF_MIN_QUALITY
        elif asset in DEFI:
            min_conf=config.DEFI_TRADE_MIN_CONFIDENCE
            min_mtf=config.DEFI_TRADE_MIN_QUALITY
        else:
            min_conf=config.MIN_TRADE_CONFIDENCE
            min_mtf=max(config.MTF_MIN_QUALITY,config.MIN_TRADE_CONFIDENCE)
        if confidence<min_conf:
            return reject("CONFIDENCE_TOO_LOW",{"confidence":confidence,"minimum":min_conf})
        if mtf_quality<min_mtf:
            return reject("MTF_QUALITY_TOO_LOW",{"mtf_quality":mtf_quality,"minimum":min_mtf})

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
    if is_micro:
        min_tp1=config.MICRO_MIN_TP1_R; min_tp2=config.MICRO_MIN_TP2_R
    elif is_scalp:
        if scalp_tier=="FAST":
            min_tp1=config.SCALP_FAST_MIN_TP1_R; min_tp2=config.SCALP_FAST_MIN_TP2_R
        else:
            min_tp1=config.SCALP_MIN_TP1_R; min_tp2=config.SCALP_MIN_TP2_R
    else:
        min_tp1=max(config.MIN_TP1_R,config.MTF_TRANSITION_MIN_TP1_R) if is_transition else config.MIN_TP1_R
        min_tp2=max(config.MIN_TP2_R,config.MTF_TRANSITION_MIN_TP2_R) if is_transition else config.MIN_TP2_R
    if rr1<min_tp1:
        return reject("TP1_REWARD_RISK_TOO_LOW",{"tp1_r":rr1,"minimum":min_tp1,"mtf_mode":mtf_mode})
    if rr2<min_tp2:
        return reject("TP2_REWARD_RISK_TOO_LOW",{"tp2_r":rr2,"minimum":min_tp2,"mtf_mode":mtf_mode})

    if config.ONE_POSITION_PER_ASSET and bool(d.get("asset_already_open",False)):
        return reject("ASSET_ALREADY_HAS_OPEN_POSITION")

    dd=max(0.0,(init-eq)/init) if init>0 else 1.0
    if dd>=config.MAX_DRAWDOWN_PCT:
        return reject("MAX_DRAWDOWN_REACHED",{"trading_halted":True})
    if float(d.get("daily_pnl",0))<=-(init*config.DAILY_LOSS_LIMIT_PCT):
        return reject("DAILY_LOSS_LIMIT_REACHED")
    max_open=config.MICRO_MAX_OPEN_POSITIONS if is_micro else config.MAX_OPEN_POSITIONS
    if int(d.get("open_positions",0))>=max_open:
        return reject("MAX_OPEN_POSITIONS_REACHED")

    dd_mult=.25 if dd>=.20 else .5 if dd>=.15 else .75 if dd>=.10 else 1.0
    stop_dist_pct=abs(entry-stop)/entry
    if stop_dist_pct<=0:return reject("INVALID_STOP_DISTANCE")
    if is_micro:
        stop_pct=stop_dist_pct*100
        if stop_pct<config.MICRO_MIN_STOP_PCT:
            return reject("MICRO_STOP_TOO_TIGHT",{"stop_pct":stop_pct,"minimum":config.MICRO_MIN_STOP_PCT})
        if stop_pct>config.MICRO_MAX_STOP_PCT:
            return reject("MICRO_STOP_TOO_WIDE",{"stop_pct":stop_pct,"maximum":config.MICRO_MAX_STOP_PCT})
    elif is_scalp:
        stop_pct=stop_dist_pct*100
        if stop_pct<config.SCALP_MIN_STOP_PCT:
            return reject("SCALP_STOP_TOO_TIGHT",{"stop_pct":stop_pct,"minimum":config.SCALP_MIN_STOP_PCT})
        if stop_pct>config.SCALP_MAX_STOP_PCT:
            return reject("SCALP_STOP_TOO_WIDE",{"stop_pct":stop_pct,"maximum":config.SCALP_MAX_STOP_PCT})

    if is_micro:
        risk_pct,quality=_micro_risk_pct(confidence,mtf_quality,dd_mult)
        if risk_pct is None:
            return reject("MICRO_TRADE_QUALITY_TOO_LOW",{"quality":quality})
    elif is_scalp:
        if scalp_tier=="FAST":
            risk_pct,quality=_scalp_fast_risk_pct(confidence,mtf_quality,dd_mult)
        else:
            risk_pct,quality=_scalp_risk_pct(confidence,mtf_quality,dd_mult)
        if risk_pct is None:
            return reject("SCALP_TRADE_QUALITY_TOO_LOW",{"quality":quality,"scalp_tier":scalp_tier})
    elif is_transition:
        quality=min(confidence,mtf_quality)
        risk_pct=min(config.MTF_TRANSITION_RISK_PCT*dd_mult,config.HARD_RISK_PCT)
    else:
        risk_pct,quality=_risk_pct(confidence,mtf_quality,dd_mult)
        if risk_pct is None:
            return reject("TRADE_QUALITY_TOO_LOW",{"quality":quality})
        if asset in DEFI:
            risk_pct=min(float(risk_pct),float(config.DEFI_TRADE_HARD_RISK_PCT))

    risk_multiplier=float(d.get("tournament_risk_multiplier") or 1.0)
    risk_multiplier=max(0.10,min(1.0,risk_multiplier))
    risk_pct=risk_pct*risk_multiplier

    risk_usd=eq*risk_pct
    leverage=_leverage(asset,d.get("volatility_regime"),quality,confidence,stop_dist_pct,strategy_mode=strategy_mode,scalp_tier=scalp_tier)

    # Notional is always risk-budgeted. Higher leverage does NOT increase risk budget.
    position_cap_pct=config.MICRO_MAX_POSITION_PCT if is_micro else config.MAX_POSITION_PCT
    notional=min(
        max(eq*config.NORMAL_POSITION_PCT,risk_usd/stop_dist_pct),
        eq*position_cap_pct
    )
    if notional*stop_dist_pct>risk_usd:
        notional=risk_usd/stop_dist_pct

    exposure_cap_pct=config.MICRO_MAX_TOTAL_EXPOSURE_PCT if is_micro else config.MAX_TOTAL_EXPOSURE_PCT
    exposure_left=max(0.0,eq*exposure_cap_pct-float(d.get("current_exposure_usd",0)))
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
        "mtf_mode":mtf_mode,
        "strategy_mode":strategy_mode,
        "scalp_tier":scalp_tier if is_scalp else None,
        "trade_quality":quality,
        "risk_pct_budget":risk_pct,
        "tournament_risk_multiplier":risk_multiplier,
        "position_notional_usd":notional,
        "actual_risk_usd":notional*stop_dist_pct,
        "actual_risk_pct":(notional*stop_dist_pct/eq) if eq>0 else 0,
        "leverage":leverage,
        "margin_required_usd":notional/leverage,
    }

if __name__=="__main__":
    d=json.load(open(sys.argv[1],encoding="utf-8")) if len(sys.argv)>1 else json.load(sys.stdin)
    print(json.dumps(evaluate(d),ensure_ascii=False,separators=(",",":")))

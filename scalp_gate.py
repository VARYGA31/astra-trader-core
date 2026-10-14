#!/usr/bin/env python3
"""Deterministic ASTRA SCALP v2 gate: 1H regime -> 15M setup -> 5M trigger.

Tiers:
- PRIME: original strict 4/5 trigger path.
- FAST: 3/5 trigger allowed only with stronger 1H+15M scores, explicit volume,
  tighter spread and smaller downstream risk.
"""
import config

def _matches(value,direction):
    return value == ("BULLISH" if direction=="LONG" else "BEARISH")

def _opposes(value,direction):
    return value == ("BEARISH" if direction=="LONG" else "BULLISH")

def _price_side(tf,direction,ema_key="ema20"):
    try:
        close=float(tf.get("close")); ema=float(tf.get("indicators",{}).get(ema_key))
        return close>ema if direction=="LONG" else close<ema
    except Exception:
        return False

def _tf_score(tf,direction):
    if tf.get("status")!="OK": return 0
    r=tf.get("regimes",{})
    pts=0
    if _matches(r.get("trend"),direction): pts+=2
    elif _opposes(r.get("trend"),direction): pts-=2
    if _matches(r.get("structure"),direction): pts+=1
    elif _opposes(r.get("structure"),direction): pts-=1
    if _matches(r.get("momentum"),direction): pts+=1
    elif _opposes(r.get("momentum"),direction): pts-=1
    pts += 1 if _price_side(tf,direction,"ema20") else -1
    return pts

def _regime_1h_ok(tf,direction):
    if tf.get("status")!="OK": return False
    r=tf.get("regimes",{})
    if _opposes(r.get("trend"),direction):
        return False
    if _matches(r.get("trend"),direction):
        return True
    return _matches(r.get("structure"),direction) and _price_side(tf,direction,"ema20")

def _setup_15m_ok(tf,direction):
    if tf.get("status")!="OK": return False
    r=tf.get("regimes",{})
    if _opposes(r.get("trend"),direction) and _opposes(r.get("structure"),direction):
        return False
    parts=[
        _matches(r.get("trend"),direction),
        _matches(r.get("structure"),direction),
        _matches(r.get("momentum"),direction),
        _price_side(tf,direction,"ema20"),
    ]
    return sum(1 for x in parts if x)>=3

def _volume_ratio(tf):
    v=tf.get("volume",{}).get("ratio_to_avg20")
    return float(v) if isinstance(v,(int,float)) else None

def _trigger_5m(tf,direction):
    if tf.get("status")!="OK":
        return {"confirmed":False,"components":{},"count":0,"volume_ratio":None}
    r=tf.get("regimes",{}); st=tf.get("structure",{}); ch=tf.get("changes_pct",{})
    ratio=_volume_ratio(tf)
    prime_volume_ok=(ratio is None) or ratio>=config.SCALP_VOLUME_MIN_RATIO
    fast_volume_ok=(ratio is not None) and ratio>=config.SCALP_FAST_VOLUME_MIN_RATIO
    if direction=="LONG":
        base={
            "price_above_ema20":_price_side(tf,"LONG","ema20"),
            "bullish_momentum":r.get("momentum")=="BULLISH",
            "bullish_structure_or_breakout":r.get("structure")=="BULLISH" or bool(st.get("breakout_up")),
            "positive_last_bar":isinstance(ch.get("1bar"),(int,float)) and ch.get("1bar")>0,
        }
    else:
        base={
            "price_below_ema20":_price_side(tf,"SHORT","ema20"),
            "bearish_momentum":r.get("momentum")=="BEARISH",
            "bearish_structure_or_breakout":r.get("structure")=="BEARISH" or bool(st.get("breakout_down")),
            "negative_last_bar":isinstance(ch.get("1bar"),(int,float)) and ch.get("1bar")<0,
        }
    # Preserve v1's five-component quality semantics: volume is the fifth component.
    components=dict(base)
    components["volume_ok"]=prime_volume_ok
    count=sum(1 for x in components.values() if x)
    price_count=sum(1 for x in base.values() if x)
    return {
        "confirmed":bool(count>=config.SCALP_TRIGGER_MIN_COMPONENTS and prime_volume_ok),
        "components":components,
        "count":count,
        "price_component_count":price_count,
        "volume_ratio":ratio,
        "prime_volume_ok":prime_volume_ok,
        "fast_volume_ok":fast_volume_ok,
    }

def _spread_pct(package):
    p=package.get("decision_context",{}).get("market",{}).get("perp_okx",{})
    try:
        bid=float(p.get("bid_price")); ask=float(p.get("ask_price")); mid=(bid+ask)/2
        return ((ask-bid)/mid*100) if mid>0 and ask>=bid else None
    except Exception:
        return None

def _volatility_ok(tf5):
    try: a=float(tf5.get("indicators",{}).get("atr_pct"))
    except Exception: return False,None
    return config.SCALP_MIN_ATR_PCT<=a<=config.SCALP_MAX_ATR_PCT,a

def _microstructure_ok(package,direction):
    spot=package.get("decision_context",{}).get("market",{}).get("spot",{})
    imb=spot.get("order_book",{}).get("imbalance")
    ratio=spot.get("trade_flow",{}).get("buy_sell_ratio")
    if direction=="LONG":
        opposed=(isinstance(imb,(int,float)) and imb<=-0.25 and isinstance(ratio,(int,float)) and ratio<=0.70)
    else:
        opposed=(isinstance(imb,(int,float)) and imb>=0.25 and isinstance(ratio,(int,float)) and ratio>=1.43)
    return not opposed,{"order_book_imbalance":imb,"buy_sell_ratio":ratio,"strongly_opposed":opposed}

def entry_guard(package,direction):
    tf5=package.get("decision_context",{}).get("market",{}).get("multi_timeframe",{}).get("frames",{}).get("5m",{})
    ind=tf5.get("indicators",{}); ch=tf5.get("changes_pct",{}); st=tf5.get("structure",{})
    rsi=ind.get("rsi14"); atr_pct=ind.get("atr_pct"); six=ch.get("6bar")
    try: price=float(tf5.get("close"))
    except Exception: price=None
    if not isinstance(rsi,(int,float)) or not isinstance(atr_pct,(int,float)) or not price:
        return {"blocked":True,"reason":"SCALP_CHASE_DATA_MISSING"}
    impulse=abs(float(six or 0)) >= config.SCALP_CHASE_IMPULSE_ATR_MULT*atr_pct
    if direction=="SHORT":
        near=st.get("distance_to_prior_low_pct")
        at_extreme=isinstance(near,(int,float)) and near<=0.20
        if rsi<=config.SCALP_SHORT_CHASE_RSI and (impulse or at_extreme):
            return {"blocked":True,"reason":"SCALP_SHORT_CHASE","rsi14":rsi,"change_6bar_pct":six,"atr_pct":atr_pct,"distance_to_prior_low_pct":near}
    if direction=="LONG":
        near=st.get("distance_to_prior_high_pct")
        at_extreme=isinstance(near,(int,float)) and near<=0.20
        if rsi>=config.SCALP_LONG_CHASE_RSI and (impulse or at_extreme):
            return {"blocked":True,"reason":"SCALP_LONG_CHASE","rsi14":rsi,"change_6bar_pct":six,"atr_pct":atr_pct,"distance_to_prior_high_pct":near}
    return {"blocked":False,"reason":"OK","rsi14":rsi,"change_6bar_pct":six,"atr_pct":atr_pct}

def _quality(frames,direction):
    s1=_tf_score(frames.get("1h",{}),direction)
    s15=_tf_score(frames.get("15m",{}),direction)
    trig=_trigger_5m(frames.get("5m",{}),direction)
    q1=max(0,min(1,s1/5))*35
    q15=max(0,min(1,s15/5))*35
    q5=(trig.get("count",0)/5)*30
    return round(q1+q15+q5,2)

def _primary_blocker(best,spread,atr_pct):
    if not best: return "SCALP_NOT_ALIGNED"
    if not best.get("regime_1h_ok"): return "SCALP_1H_REGIME_BLOCK"
    if not best.get("setup_15m_ok"): return "SCALP_15M_SETUP_BLOCK"
    trig=best.get("trigger_5m",{})
    if trig.get("count",0)<config.SCALP_FAST_TRIGGER_MIN_COMPONENTS:
        return "SCALP_5M_TRIGGER_BLOCK"
    if config.SCALP_FAST_ENABLED and not trig.get("fast_volume_ok") and not best.get("prime_pass"):
        return "SCALP_5M_VOLUME_BLOCK"
    if not best.get("microstructure_ok"): return "SCALP_MICROSTRUCTURE_BLOCK"
    if best.get("quality",0)<config.SCALP_FAST_MIN_QUALITY: return "SCALP_QUALITY_BLOCK"
    return "SCALP_NOT_ALIGNED"

def evaluate(package):
    asset=str(package.get("asset","")).upper()
    if asset not in set(config.SCALP_ALLOWED_ASSETS):
        return {"passed":False,"direction":None,"quality":0,"reason":"SCALP_ASSET_NOT_ALLOWED","mode":"SCALP","tier":None}
    mtf=package.get("decision_context",{}).get("market",{}).get("multi_timeframe",{})
    frames=mtf.get("frames",{})
    for req in ("5m","15m","1h"):
        if frames.get(req,{}).get("status")!="OK":
            return {"passed":False,"direction":None,"quality":0,"reason":"SCALP_MTF_DATA_FAILED","missing_frame":req,"mode":"SCALP","tier":None}

    spread=_spread_pct(package)
    if spread is None or spread>config.SCALP_MAX_SPREAD_PCT:
        return {"passed":False,"direction":None,"quality":0,"reason":"SCALP_SPREAD_TOO_WIDE","primary_blocker":"SCALP_SPREAD_TOO_WIDE","spread_pct":spread,"maximum_pct":config.SCALP_MAX_SPREAD_PCT,"mode":"SCALP","tier":None}
    vol_ok,atr_pct=_volatility_ok(frames.get("5m",{}))
    if not vol_ok:
        return {"passed":False,"direction":None,"quality":0,"reason":"SCALP_VOLATILITY_OUT_OF_RANGE","primary_blocker":"SCALP_VOLATILITY_OUT_OF_RANGE","atr_pct":atr_pct,"minimum":config.SCALP_MIN_ATR_PCT,"maximum":config.SCALP_MAX_ATR_PCT,"mode":"SCALP","tier":None}

    candidates=[]
    for direction in ("LONG","SHORT"):
        tf1=frames.get("1h",{}); tf15=frames.get("15m",{}); tf5=frames.get("5m",{})
        score1=_tf_score(tf1,direction); score15=_tf_score(tf15,direction)
        r1=_regime_1h_ok(tf1,direction)
        s15=_setup_15m_ok(tf15,direction)
        t5=_trigger_5m(tf5,direction)
        micro_ok,micro=_microstructure_ok(package,direction)
        q=_quality(frames,direction)
        prime_pass=bool(
            r1 and s15 and t5.get("confirmed") and micro_ok
            and q>=config.SCALP_MIN_QUALITY
        )
        fast_pass=bool(
            config.SCALP_FAST_ENABLED
            and r1 and s15 and micro_ok
            and t5.get("count",0)>=config.SCALP_FAST_TRIGGER_MIN_COMPONENTS
            and t5.get("fast_volume_ok")
            and spread<=config.SCALP_FAST_MAX_SPREAD_PCT
            and score1>=config.SCALP_FAST_MIN_1H_SCORE
            and score15>=config.SCALP_FAST_MIN_15M_SCORE
            and q>=config.SCALP_FAST_MIN_QUALITY
        )
        candidates.append({
            "direction":direction,
            "passed":bool(prime_pass or fast_pass),
            "mode":"SCALP",
            "tier":"PRIME" if prime_pass else "FAST" if fast_pass else None,
            "quality":q,
            "score_1h":score1,"score_15m":score15,
            "regime_1h_ok":r1,"setup_15m_ok":s15,"trigger_5m":t5,
            "microstructure_ok":micro_ok,"microstructure":micro,
            "prime_pass":prime_pass,"fast_pass":fast_pass,
        })

    primes=[x for x in candidates if x.get("prime_pass")]
    fasts=[x for x in candidates if x.get("fast_pass")]
    chosen=(max(primes,key=lambda x:x.get("quality",0)) if primes else (max(fasts,key=lambda x:x.get("quality",0)) if fasts else None))
    best=max(candidates,key=lambda x:x.get("quality",0)) if candidates else None
    blocker=_primary_blocker(best,spread,atr_pct) if not chosen else None
    tf5=frames.get("5m",{})
    tier=chosen.get("tier") if chosen else None
    min_q=(config.SCALP_MIN_QUALITY if tier=="PRIME" else config.SCALP_FAST_MIN_QUALITY if tier=="FAST" else config.SCALP_FAST_MIN_QUALITY)
    return {
        "passed":bool(chosen),
        "direction":chosen.get("direction") if chosen else None,
        "mode":"SCALP",
        "tier":tier,
        "quality":chosen.get("quality") if chosen else (best.get("quality") if best else 0),
        "minimum_quality":min_q,
        "prime_minimum_quality":config.SCALP_MIN_QUALITY,
        "fast_minimum_quality":config.SCALP_FAST_MIN_QUALITY,
        "reason":"SCALP_ALIGNED" if chosen else "SCALP_NOT_ALIGNED",
        "primary_blocker":blocker,
        "trigger_candle_id":tf5.get("last_confirmed_close_time_ms"),
        "spread_pct":spread,
        "atr_pct_5m":atr_pct,
        "frames_summary":{
            k:{
                "trend":v.get("regimes",{}).get("trend"),
                "structure":v.get("regimes",{}).get("structure"),
                "momentum":v.get("regimes",{}).get("momentum"),
                "rsi14":v.get("indicators",{}).get("rsi14"),
                "atr_pct":v.get("indicators",{}).get("atr_pct"),
                "change_1bar":v.get("changes_pct",{}).get("1bar"),
                "volume_ratio":v.get("volume",{}).get("ratio_to_avg20"),
            } for k,v in frames.items() if k in {"5m","15m","1h"}
        },
        "candidates":candidates,
    }

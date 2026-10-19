#!/usr/bin/env python3
"""Deterministic ASTRA MICRO v1 gate: 5m context -> 3m setup -> 1m trigger.

MICRO is intentionally demo-first. It looks for short-lived momentum/structure
alignment while retaining hard spread, volatility, chase and microstructure
guards before ASTRA is called.
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
    if tf.get("status")!="OK":
        return -5
    r=tf.get("regimes",{})
    pts=0
    if _matches(r.get("trend"),direction): pts+=2
    elif _opposes(r.get("trend"),direction): pts-=2
    if _matches(r.get("structure"),direction): pts+=1
    elif _opposes(r.get("structure"),direction): pts-=1
    if _matches(r.get("momentum"),direction): pts+=1
    elif _opposes(r.get("momentum"),direction): pts-=1
    pts += 1 if _price_side(tf,direction) else -1
    return pts

def _spread_pct(package):
    p=package.get("decision_context",{}).get("market",{}).get("perp_okx",{})
    try:
        bid=float(p.get("bid_price")); ask=float(p.get("ask_price")); mid=(bid+ask)/2
        return ((ask-bid)/mid*100) if mid>0 and ask>=bid else None
    except Exception:
        return None

def _microstructure(package,direction):
    spot=package.get("decision_context",{}).get("market",{}).get("spot",{})
    imb=spot.get("order_book",{}).get("imbalance")
    ratio=spot.get("trade_flow",{}).get("buy_sell_ratio")
    if direction=="LONG":
        opposed=(isinstance(imb,(int,float)) and imb<=-0.22 and isinstance(ratio,(int,float)) and ratio<=0.75)
        aligned=(isinstance(imb,(int,float)) and imb>=0.08) or (isinstance(ratio,(int,float)) and ratio>=1.08)
    else:
        opposed=(isinstance(imb,(int,float)) and imb>=0.22 and isinstance(ratio,(int,float)) and ratio>=1.33)
        aligned=(isinstance(imb,(int,float)) and imb<=-0.08) or (isinstance(ratio,(int,float)) and ratio<=0.93)
    return {
        "ok":not opposed,
        "aligned":bool(aligned),
        "order_book_imbalance":imb,
        "buy_sell_ratio":ratio,
        "strongly_opposed":opposed,
    }

def _trigger_1m(tf,direction):
    if tf.get("status")!="OK":
        return {"confirmed":False,"count":0,"components":{},"volume_ratio":None}
    r=tf.get("regimes",{}); st=tf.get("structure",{}); ch=tf.get("changes_pct",{})
    ratio=tf.get("volume",{}).get("ratio_to_avg20")
    volume_ok=isinstance(ratio,(int,float)) and ratio>=config.MICRO_VOLUME_MIN_RATIO
    if direction=="LONG":
        components={
            "price_above_ema20":_price_side(tf,"LONG"),
            "bullish_momentum":r.get("momentum")=="BULLISH",
            "bullish_structure_or_breakout":r.get("structure")=="BULLISH" or bool(st.get("breakout_up")),
            "positive_last_bar":isinstance(ch.get("1bar"),(int,float)) and ch.get("1bar")>0,
            "volume_expansion":volume_ok,
        }
    else:
        components={
            "price_below_ema20":_price_side(tf,"SHORT"),
            "bearish_momentum":r.get("momentum")=="BEARISH",
            "bearish_structure_or_breakout":r.get("structure")=="BEARISH" or bool(st.get("breakout_down")),
            "negative_last_bar":isinstance(ch.get("1bar"),(int,float)) and ch.get("1bar")<0,
            "volume_expansion":volume_ok,
        }
    count=sum(1 for x in components.values() if x)
    return {
        "confirmed":count>=config.MICRO_TRIGGER_MIN_COMPONENTS and volume_ok,
        "count":count,
        "components":components,
        "volume_ratio":ratio,
    }

def entry_guard(package,direction):
    frames=package.get("decision_context",{}).get("market",{}).get("multi_timeframe",{}).get("frames",{})
    tf1=frames.get("1m",{})
    rsi=tf1.get("indicators",{}).get("rsi14")
    atr_pct=tf1.get("indicators",{}).get("atr_pct")
    three=tf1.get("changes_pct",{}).get("3bar")
    st=tf1.get("structure",{})
    if not isinstance(rsi,(int,float)) or not isinstance(atr_pct,(int,float)):
        return {"blocked":True,"reason":"MICRO_CHASE_DATA_MISSING"}
    impulse=abs(float(three or 0)) >= config.MICRO_CHASE_IMPULSE_ATR_MULT*atr_pct
    if direction=="LONG":
        near=st.get("distance_to_prior_high_pct")
        extreme=isinstance(near,(int,float)) and near<=config.MICRO_EXTREME_DISTANCE_PCT
        if rsi>=config.MICRO_LONG_CHASE_RSI and (impulse or extreme):
            return {"blocked":True,"reason":"MICRO_LONG_CHASE","rsi14":rsi,"change_3bar_pct":three,"atr_pct":atr_pct}
    else:
        near=st.get("distance_to_prior_low_pct")
        extreme=isinstance(near,(int,float)) and near<=config.MICRO_EXTREME_DISTANCE_PCT
        if rsi<=config.MICRO_SHORT_CHASE_RSI and (impulse or extreme):
            return {"blocked":True,"reason":"MICRO_SHORT_CHASE","rsi14":rsi,"change_3bar_pct":three,"atr_pct":atr_pct}
    return {"blocked":False,"reason":"OK","rsi14":rsi,"change_3bar_pct":three,"atr_pct":atr_pct}

def evaluate(package):
    asset=str(package.get("asset","")).upper()
    if asset not in set(config.MICRO_ALLOWED_ASSETS):
        return {"passed":False,"direction":None,"quality":0,"reason":"MICRO_ASSET_NOT_ALLOWED","mode":"MICRO"}

    frames=package.get("decision_context",{}).get("market",{}).get("multi_timeframe",{}).get("frames",{})
    for req in ("1m","3m","5m"):
        if frames.get(req,{}).get("status")!="OK":
            return {"passed":False,"direction":None,"quality":0,"reason":"MICRO_MTF_DATA_FAILED","missing_frame":req,"mode":"MICRO"}

    spread=_spread_pct(package)
    if spread is None or spread>config.MICRO_MAX_SPREAD_PCT:
        return {"passed":False,"direction":None,"quality":0,"reason":"MICRO_SPREAD_TOO_WIDE","spread_pct":spread,"maximum_pct":config.MICRO_MAX_SPREAD_PCT,"mode":"MICRO"}

    try:
        atr_pct=float(frames["1m"].get("indicators",{}).get("atr_pct"))
    except Exception:
        atr_pct=None
    if atr_pct is None or not (config.MICRO_MIN_ATR_PCT<=atr_pct<=config.MICRO_MAX_ATR_PCT):
        return {"passed":False,"direction":None,"quality":0,"reason":"MICRO_VOLATILITY_OUT_OF_RANGE","atr_pct":atr_pct,"mode":"MICRO"}

    candidates=[]
    for direction in ("LONG","SHORT"):
        s5=_tf_score(frames["5m"],direction)
        s3=_tf_score(frames["3m"],direction)
        trig=_trigger_1m(frames["1m"],direction)
        micro=_microstructure(package,direction)
        context_ok=s5>=0 and not (_opposes(frames["5m"].get("regimes",{}).get("trend"),direction) and s5<0)
        setup_ok=s3>=2
        q5=max(0.0,min(1.0,(s5+1)/6.0))*25.0
        q3=max(0.0,min(1.0,(s3+1)/6.0))*30.0
        q1=(trig.get("count",0)/5.0)*35.0
        qm=10.0 if micro.get("aligned") else 5.0 if micro.get("ok") else 0.0
        quality=round(q5+q3+q1+qm,2)
        passed=bool(context_ok and setup_ok and trig.get("confirmed") and micro.get("ok") and quality>=config.MICRO_MIN_QUALITY)
        candidates.append({
            "direction":direction,
            "passed":passed,
            "quality":quality,
            "score_5m":s5,
            "score_3m":s3,
            "context_5m_ok":context_ok,
            "setup_3m_ok":setup_ok,
            "trigger_1m":trig,
            "microstructure":micro,
        })

    passed=[x for x in candidates if x.get("passed")]
    chosen=max(passed,key=lambda x:x["quality"]) if passed else None
    best=max(candidates,key=lambda x:x["quality"])
    return {
        "passed":bool(chosen),
        "direction":chosen.get("direction") if chosen else None,
        "quality":chosen.get("quality") if chosen else best.get("quality",0),
        "minimum_quality":config.MICRO_MIN_QUALITY,
        "reason":"MICRO_ALIGNED" if chosen else "MICRO_NOT_ALIGNED",
        "mode":"MICRO",
        "trigger_candle_id":frames["1m"].get("last_confirmed_close_time_ms"),
        "spread_pct":spread,
        "atr_pct_1m":atr_pct,
        "candidates":candidates,
    }

#!/usr/bin/env python3
import config

def _matches(value, direction):
    return value == ("BULLISH" if direction=="LONG" else "BEARISH")

def _opposes(value, direction):
    return value == ("BEARISH" if direction=="LONG" else "BULLISH")

def _price_side(tf, direction, ema_key="ema20"):
    try:
        close=float(tf.get("close"))
        ema=float(tf.get("indicators",{}).get(ema_key))
        return close > ema if direction=="LONG" else close < ema
    except Exception:
        return False

def _tf_score(tf, direction):
    if tf.get("status")!="OK":
        return 0, []
    r=tf.get("regimes",{})
    pts=0; reasons=[]
    if _matches(r.get("trend"),direction):
        pts+=2; reasons.append("trend")
    elif _opposes(r.get("trend"),direction):
        pts-=2; reasons.append("trend_opposes")
    if _matches(r.get("structure"),direction):
        pts+=1; reasons.append("structure")
    elif _opposes(r.get("structure"),direction):
        pts-=1; reasons.append("structure_opposes")
    if _matches(r.get("momentum"),direction):
        pts+=1; reasons.append("momentum")
    elif _opposes(r.get("momentum"),direction):
        pts-=1; reasons.append("momentum_opposes")
    if _price_side(tf,direction,"ema20"):
        pts+=1; reasons.append("price_ema20")
    else:
        pts-=1; reasons.append("price_ema20_opposes")
    return pts,reasons

def _regime_ok(tf4, direction):
    if tf4.get("status")!="OK":
        return False
    r=tf4.get("regimes",{})
    # Strong preference: 4H trend matches.
    if _matches(r.get("trend"),direction):
        return True
    # Allow a developing regime only when structure and EMA50 side both agree.
    return _matches(r.get("structure"),direction) and _price_side(tf4,direction,"ema50")

def _setup_ok(tf1, direction):
    if tf1.get("status")!="OK":
        return False
    r=tf1.get("regimes",{})
    if _opposes(r.get("trend"),direction) and _opposes(r.get("structure"),direction):
        return False
    components=[
        _matches(r.get("trend"),direction),
        _matches(r.get("structure"),direction),
        _matches(r.get("momentum"),direction),
        _price_side(tf1,direction,"ema20"),
    ]
    return sum(1 for x in components if x) >= 3

def _trigger(tf15, direction):
    if tf15.get("status")!="OK":
        return {"confirmed":False,"components":{}, "count":0}
    r=tf15.get("regimes",{})
    st=tf15.get("structure",{})
    ch=tf15.get("changes_pct",{})
    vol=tf15.get("volume",{})

    if direction=="LONG":
        components={
            "price_above_ema20":_price_side(tf15,"LONG","ema20"),
            "bullish_momentum":r.get("momentum")=="BULLISH",
            "bullish_structure_or_breakout":r.get("structure")=="BULLISH" or bool(st.get("breakout_up")),
            "positive_last_bar":isinstance(ch.get("1bar"),(int,float)) and ch.get("1bar")>0,
            "volume_not_dead":not isinstance(vol.get("ratio_to_avg20"),(int,float)) or vol.get("ratio_to_avg20")>=0.70,
        }
    else:
        components={
            "price_below_ema20":_price_side(tf15,"SHORT","ema20"),
            "bearish_momentum":r.get("momentum")=="BEARISH",
            "bearish_structure_or_breakout":r.get("structure")=="BEARISH" or bool(st.get("breakout_down")),
            "negative_last_bar":isinstance(ch.get("1bar"),(int,float)) and ch.get("1bar")<0,
            "volume_not_dead":not isinstance(vol.get("ratio_to_avg20"),(int,float)) or vol.get("ratio_to_avg20")>=0.70,
        }
    count=sum(1 for x in components.values() if x)
    # volume_not_dead is a veto-style component; 3/5 minimum by default.
    confirmed=count>=config.MTF_TRIGGER_MIN_COMPONENTS and components.get("volume_not_dead",True)
    return {"confirmed":confirmed,"components":components,"count":count}

def _quality(frames, direction):
    tf4=frames.get("4h",{}); tf1=frames.get("1h",{}); tf15=frames.get("15m",{})
    s4,_=_tf_score(tf4,direction)
    s1,_=_tf_score(tf1,direction)
    s15,_=_tf_score(tf15,direction)
    trig=_trigger(tf15,direction)

    # 4H 35%, 1H 35%, 15M trigger 30%.
    # tf score is roughly -5..5; convert only positive alignment to quality.
    q4=max(0,min(1,s4/5))*35
    q1=max(0,min(1,s1/5))*35
    q15=(trig["count"]/5)*30
    return round(q4+q1+q15,2)

def evaluate(package):
    mtf=package.get("decision_context",{}).get("market",{}).get("multi_timeframe",{})
    frames=mtf.get("frames",{})
    if not config.MTF_ENABLED:
        return {"passed":True,"direction":None,"quality":100,"reason":"MTF_DISABLED"}
    if mtf.get("status")=="FAILED":
        return {"passed":False,"direction":None,"quality":0,"reason":"MTF_DATA_FAILED"}

    candidates=[]
    for direction in ("LONG","SHORT"):
        regime_ok=_regime_ok(frames.get("4h",{}),direction)
        setup_ok=_setup_ok(frames.get("1h",{}),direction)
        trigger=_trigger(frames.get("15m",{}),direction)
        quality=_quality(frames,direction)
        passed=bool(regime_ok and setup_ok and trigger["confirmed"] and quality>=config.MTF_MIN_QUALITY)
        candidates.append({
            "direction":direction,
            "passed":passed,
            "quality":quality,
            "regime_4h_ok":regime_ok,
            "setup_1h_ok":setup_ok,
            "trigger_15m":trigger,
        })

    passed=[x for x in candidates if x["passed"]]
    best=max(candidates,key=lambda x:x["quality"]) if candidates else None
    chosen=max(passed,key=lambda x:x["quality"]) if passed else None

    tf15=frames.get("15m",{})
    return {
        "passed":bool(chosen),
        "direction":chosen["direction"] if chosen else None,
        "quality":chosen["quality"] if chosen else (best["quality"] if best else 0),
        "reason":"MTF_ALIGNED" if chosen else "MTF_NOT_ALIGNED",
        "trigger_candle_id":tf15.get("last_confirmed_close_time_ms"),
        "frames_summary":{
            k:{
                "trend":v.get("regimes",{}).get("trend"),
                "structure":v.get("regimes",{}).get("structure"),
                "momentum":v.get("regimes",{}).get("momentum"),
                "rsi14":v.get("indicators",{}).get("rsi14"),
                "atr_pct":v.get("indicators",{}).get("atr_pct"),
                "change_1bar":v.get("changes_pct",{}).get("1bar"),
                "breakout_up":v.get("structure",{}).get("breakout_up"),
                "breakout_down":v.get("structure",{}).get("breakout_down"),
                "volume_ratio":v.get("volume",{}).get("ratio_to_avg20"),
            } for k,v in frames.items()
        },
        "candidates":candidates,
    }

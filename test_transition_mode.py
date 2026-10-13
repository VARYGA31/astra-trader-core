#!/usr/bin/env python3
"""Pure-function transition-mode test. Opens/closes no orders and calls no model."""
import json
import config
import mtf_gate
import risk_engine


def tf(trend,structure,momentum,close,ema20,ema50,rsi=55,change=0.2,breakout_up=False,breakout_down=False,vol=1.0):
    return {
        "status":"OK","close":close,
        "indicators":{"ema20":ema20,"ema50":ema50,"ema200":ema50-2,"rsi14":rsi,"atr_pct":0.8},
        "regimes":{"trend":trend,"structure":structure,"momentum":momentum},
        "structure":{"breakout_up":breakout_up,"breakout_down":breakout_down},
        "changes_pct":{"1bar":change},
        "volume":{"ratio_to_avg20":vol},
        "last_confirmed_close_time_ms":123,
    }


def package(asset,frames):
    return {"asset":asset,"decision_context":{"market":{"multi_timeframe":{"status":"OK","frames":frames}}}}

# Transition LONG: 4H MIXED but non-opposite/supportive, strong 1H and 15M.
frames_transition={
    # Price has reclaimed EMA20 but not EMA50 yet: current NORMAL regime gate stays false,
    # while the transitional 4H evidence is supportive and non-opposite.
    "4h":tf("MIXED","BULLISH","NEUTRAL",103,102,104,rsi=52,change=0.1),
    "1h":tf("BULLISH","BULLISH","BULLISH",105,103,101,rsi=61,change=0.5),
    "15m":tf("BULLISH","BULLISH","BULLISH",105,104,103,rsi=60,change=0.25,breakout_up=True,vol=1.2),
}
t=mtf_gate.evaluate(package("BTC",frames_transition))
assert t["passed"] is True, t
assert t["mode"]=="TRANSITION", t
assert t["direction"]=="LONG", t
assert t["quality"]>=config.MTF_TRANSITION_MIN_QUALITY, t

# Clearly opposite 4H must NOT be admitted as transition.
frames_opposite=dict(frames_transition)
frames_opposite["4h"]=tf("BEARISH","BEARISH","BEARISH",95,100,102,rsi=40,change=-0.4)
o=mtf_gate.evaluate(package("BTC",frames_opposite))
assert not (o.get("passed") and o.get("direction")=="LONG"), o

# XAU must remain on the original strict path; no transition mode.
x=mtf_gate.evaluate(package("XAU",frames_transition))
assert x.get("mode")!="TRANSITION", x

# Transition risk: confidence threshold + conservative risk budget.
base={
    "asset":"BTC","action":"LONG","equity":5000,"initial_equity":5000,"daily_pnl":0,
    "open_positions":0,"current_exposure_usd":0,"asset_already_open":False,
    "critical_news_verified":True,"data_quality":"OK","volatility_regime":"NORMAL",
    "entry":100,"stop_loss":98,"take_profit_1":102.5,"take_profit_2":104.2,
    "mtf_quality":max(config.MTF_TRANSITION_MIN_QUALITY,60),"mtf_mode":"TRANSITION",
}
low=dict(base,confidence=config.MTF_TRANSITION_MIN_CONFIDENCE-1)
r0=risk_engine.evaluate(low)
assert r0.get("status")=="REJECTED" and r0.get("reason")=="TRANSITION_CONFIDENCE_TOO_LOW", r0

ok=dict(base,confidence=max(config.MTF_TRANSITION_MIN_CONFIDENCE,92))
r1=risk_engine.evaluate(ok)
assert r1.get("status")=="APPROVED", r1
assert r1.get("mtf_mode")=="TRANSITION", r1
assert r1.get("actual_risk_pct") <= config.MTF_TRANSITION_RISK_PCT + 1e-12, r1

print(json.dumps({
    "status":"OK",
    "will_open_order":False,
    "will_close_order":False,
    "will_call_model":False,
    "transition_gate":t,
    "opposite_4h_blocked":True,
    "xau_transition_disabled":True,
    "transition_risk":{
        "risk_pct_budget":r1.get("risk_pct_budget"),
        "actual_risk_pct":r1.get("actual_risk_pct"),
        "leverage":r1.get("leverage"),
        "min_confidence":config.MTF_TRANSITION_MIN_CONFIDENCE,
    },
},ensure_ascii=False,indent=2))

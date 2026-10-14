import json,re
from pathlib import Path
from datetime import datetime,timezone
from openai import OpenAI
import config

NORMAL_POLICY = """
FINAL DECISION CALIBRATION POLICY:
- The Python gate already performs 4H regime -> 1H setup -> 15M trigger filtering.
- NORMAL mode: when mtf.passed=true, allowed_direction is LONG/SHORT, confidence is at or above the supplied normal minimum, and there is NO concrete hard invalidator, choose the allowed direction. WAIT is an exception, not the default.
- Do NOT WAIT merely because a pullback/retest might be nicer, because momentum is not perfect, because another candle could add confirmation, or because price could retrace. Those are preferences, not hard invalidators after a valid NORMAL gate.
- NORMAL WAIT is allowed only for a concrete blocker supported by supplied data: CHASE_RISK, STRUCTURE_CONFLICT, NEWS_RISK, VOLATILITY_RISK, RR_OR_STOP_INVALID, REVERSAL_RISK, DATA_QUALITY, or XAU_MACRO_RISK.
- TRANSITION remains conservative: require confidence >= the supplied transition minimum; TRANSITION_WEAK is a valid WAIT category.
- Never invent a blocker. Name the exact supplied evidence in reason.
"""

SCALP_POLICY = """
ASTRA SCALP v2 FINAL DECISION POLICY:
- The Python gate already performs 1H regime -> 15M setup -> 5M trigger filtering and assigns a tier: PRIME or FAST.
- PRIME is the stricter 5M trigger path. FAST intentionally accepts a 3/5 trigger only when higher-timeframe alignment, volume, spread and microstructure are stronger; downstream Python reduces FAST risk and leverage.
- You are deciding a short-horizon scalp, not a swing trade. Use only the allowed_direction supplied by the gate.
- A valid SCALP gate is actionable unless supplied data shows a concrete hard invalidator. Do not WAIT merely because FAST has 3/5 instead of 4/5, and do not WAIT merely for another candle or a nicer retest after the deterministic gate passed.
- PRIME requires at least the supplied PRIME confidence minimum. FAST requires the supplied higher FAST confidence minimum.
- Respect the 5M/15M structure. Stop must sit beyond a logical short-horizon invalidation; do not make it artificially tight.
- Targets must be realistic for a scalp and must satisfy at least the supplied SCALP R:R minimums.
- WAIT only for concrete CHASE_RISK, STRUCTURE_CONFLICT, NEWS_RISK, VOLATILITY_RISK, LIQUIDITY_SPREAD_RISK, RR_OR_STOP_INVALID, REVERSAL_RISK, or DATA_QUALITY.
- Never invent a blocker. Name the exact supplied evidence in reason.
"""

DECISION_POLICY = NORMAL_POLICY

BASE_INSTRUCTIONS="""You are ASTRA TRADER's final trade decision engine.
Trade only assets explicitly allowed by the deterministic package. Return exactly one JSON object.

The deterministic Python strategy gate, anti-chase rules, portfolio guards, Risk Engine,
and execution-quality FOK guard have authority over you. Never override them.
Never size a position. Never choose position notional.
Confidence is analytical confidence 0-100, NOT win probability.
Leverage is chosen by deterministic Python, not by you.
News is context, not an automatic BUY/SELL instruction.

ENTRY PRICE RULE:
When market.perp_okx.last_price is available, use that OKX perpetual price as the tradable entry reference.
The Python execution layer will re-check the live OKX price and may cancel the trade if R:R or fill quality deteriorates.

Required JSON keys:
asset, action, entry, stop_loss, take_profit_1, take_profit_2,
confidence, data_quality, volatility_regime, setup_type, reason,
wait_category, wait_is_hard_blocker.

action: LONG | SHORT | WAIT.
setup_type examples: PULLBACK_CONTINUATION, BREAKOUT_RETEST, TREND_CONTINUATION, MOMENTUM_SCALP, NONE.
WAIT categories:
NONE | CHASE_RISK | STRUCTURE_CONFLICT | NEWS_RISK | VOLATILITY_RISK |
LIQUIDITY_SPREAD_RISK | RR_OR_STOP_INVALID | REVERSAL_RISK | DATA_QUALITY |
XAU_MACRO_RISK | TRANSITION_WEAK.
For LONG/SHORT: wait_category=NONE and wait_is_hard_blocker=false.
For WAIT: entry/stop/take profits=null and identify the concrete blocker.
For LONG: stop < entry < TP1 < TP2. For SHORT: stop > entry > TP1 > TP2.
Do not invent unavailable data.
"""

def extract(text):
    try:return json.loads(text)
    except:
        m=re.search(r"\{.*\}",text,re.S)
        if not m:raise ValueError("Model did not return JSON")
        return json.loads(m.group(0))

def _compact_mtf(mtf,mode):
    if not isinstance(mtf,dict): return mtf
    keep={"5m","15m","1h"} if mode=="SCALP" else {"15m","1h","4h"}
    out=dict(mtf)
    frames=mtf.get("frames") or {}
    out["frames"]={k:v for k,v in frames.items() if k in keep}
    return out

def _compact(p):
    dc=p.get("decision_context",{}); m=dc.get("market",{}); n=dc.get("news",{})
    mode=str(p.get("strategy_mode") or "NORMAL").upper()
    ev=[]
    for e in n.get("events",[])[:config.MAX_MODEL_NEWS_EVENTS]:
        ev.append({k:e.get(k) for k in ("id","source","verification_status","published_at_utc","title","event_type","impact_hint","trade_usable")})
    policy={
        "version":"scalp_v2" if mode=="SCALP" else "normal_cal_v1",
        "strategy_mode":mode,
        "normal_min_trade_confidence":config.MIN_TRADE_CONFIDENCE,
        "transition_min_trade_confidence":config.MTF_TRANSITION_MIN_CONFIDENCE,
        "xau_min_trade_confidence":config.XAU_MIN_TRADE_CONFIDENCE,
        "scalp_prime_min_trade_confidence":config.SCALP_MIN_TRADE_CONFIDENCE,
        "scalp_fast_min_trade_confidence":config.SCALP_FAST_MIN_TRADE_CONFIDENCE,
        "scalp_prime_min_tp1_r":config.SCALP_MIN_TP1_R,
        "scalp_prime_min_tp2_r":config.SCALP_MIN_TP2_R,
        "scalp_fast_min_tp1_r":config.SCALP_FAST_MIN_TP1_R,
        "scalp_fast_min_tp2_r":config.SCALP_FAST_MIN_TP2_R,
        "wait_requires_concrete_blocker":True,
    }
    return {
        "asset":p.get("asset"),"timeframe":p.get("timeframe"),"strategy_mode":mode,
        "execution_mode":p.get("execution_mode"),"account_state":p.get("account_state"),"guards":p.get("guards"),
        "model_gate":p.get("model_gate"),"decision_policy":policy,
        "market":{
            "generated_at_utc":m.get("generated_at_utc"),"spot":m.get("spot"),
            "multi_timeframe":_compact_mtf(m.get("multi_timeframe"),mode),
            "perp_okx":m.get("perp_okx"),"gold_macro":m.get("gold_macro") if mode!="SCALP" else None,
            "data_quality":m.get("data_quality"),
        },
        "news":{"summary":n.get("summary"),"guard":n.get("guard"),"events":ev},
    }

def _log_usage(r,asset,mode):
    u=getattr(r,"usage",None)
    if not u:return
    row={"timestamp_utc":datetime.now(timezone.utc).isoformat(),"asset":asset,"strategy_mode":mode,"model":config.OPENAI_MODEL,
         "input_tokens":getattr(u,"input_tokens",None),"output_tokens":getattr(u,"output_tokens",None),"total_tokens":getattr(u,"total_tokens",None)}
    try:
        path=Path(config.STATE_DIR)/"openai_usage.jsonl"; path.parent.mkdir(parents=True,exist_ok=True)
        with path.open("a",encoding="utf-8") as f:f.write(json.dumps(row,ensure_ascii=False)+"\n")
    except Exception:pass

ALLOWED_WAIT_CATEGORIES={"NONE","CHASE_RISK","STRUCTURE_CONFLICT","NEWS_RISK","VOLATILITY_RISK","LIQUIDITY_SPREAD_RISK","RR_OR_STOP_INVALID","REVERSAL_RISK","DATA_QUALITY","XAU_MACRO_RISK","TRANSITION_WEAK"}

def _normalize_decision(d,package):
    mode=str(package.get("strategy_mode") or "NORMAL").upper()
    try:
        c=float(d.get("confidence",0)); d["confidence"]=max(0,min(100,c*100 if 0<=c<=1 else c))
    except Exception:d["confidence"]=0.0
    a=str(d.get("action","WAIT")).upper(); d["action"]=a if a in {"LONG","SHORT","WAIT"} else "WAIT"
    d["asset"]=str(d.get("asset",package.get("asset",""))).upper()
    d["timeframe"]=d.get("timeframe") or package.get("timeframe") or ("5m" if mode=="SCALP" else config.TRADING_TIMEFRAME)
    d["strategy_mode"]=mode
    d["setup_type"]=str(d.get("setup_type","NONE")).upper()
    d["decision_policy_version"]="scalp_v2" if mode=="SCALP" else "normal_cal_v1"
    if mode=="SCALP":
        d["scalp_tier"]=str(package.get("model_gate",{}).get("scalp_tier") or package.get("model_gate",{}).get("mtf",{}).get("tier") or "PRIME").upper()
    cat=str(d.get("wait_category") or "NONE").upper().strip()
    if cat not in ALLOWED_WAIT_CATEGORIES:cat="UNSPECIFIED"
    if d["action"]=="WAIT":
        d["entry"]=None; d["stop_loss"]=None; d["take_profit_1"]=None; d["take_profit_2"]=None
        d["wait_category"]=cat if cat!="NONE" else "UNSPECIFIED"
        d["wait_is_hard_blocker"]=bool(d.get("wait_is_hard_blocker",False))
    else:
        d["wait_category"]="NONE"; d["wait_is_hard_blocker"]=False
    return d

def decide(package):
    mode=str(package.get("strategy_mode") or "NORMAL").upper()
    policy=SCALP_POLICY if mode=="SCALP" else NORMAL_POLICY
    instructions=BASE_INSTRUCTIONS+"\n"+policy
    client=OpenAI(); compact=_compact(package)
    kwargs={
        "input":"Apply this strategy policy exactly:\n"+policy+"\nAnalyze this pre-filtered trading context and return the required JSON only:\n"+json.dumps(compact,ensure_ascii=False,separators=(",",":")),
        "store":False,
    }
    if config.OPENAI_PROMPT_ID:
        kwargs["prompt"]={"id":config.OPENAI_PROMPT_ID}
    else:
        kwargs["model"]=config.OPENAI_MODEL; kwargs["instructions"]=instructions; kwargs["reasoning"]={"effort":config.OPENAI_REASONING_EFFORT}
    r=client.responses.create(**kwargs)
    _log_usage(r,package.get("asset"),mode)
    return _normalize_decision(extract(r.output_text),package)

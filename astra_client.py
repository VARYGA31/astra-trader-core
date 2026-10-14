import json,re
from pathlib import Path
from datetime import datetime,timezone
from openai import OpenAI
import config

DECISION_POLICY = """
FINAL DECISION CALIBRATION POLICY:
- The Python gate already performs 4H regime -> 1H setup -> 15M trigger filtering.
- NORMAL mode: when mtf.passed=true, allowed_direction is LONG/SHORT, confidence is at or above the supplied normal minimum, and there is NO concrete hard invalidator, choose the allowed direction. WAIT is an exception, not the default.
- Do NOT WAIT merely because a pullback/retest might be nicer, because momentum is not perfect, because another candle could add confirmation, or because price could retrace. Those are preferences, not hard invalidators after a valid NORMAL gate.
- NORMAL WAIT is allowed only for a concrete blocker supported by supplied data: CHASE_RISK, STRUCTURE_CONFLICT, NEWS_RISK, VOLATILITY_RISK, RR_OR_STOP_INVALID, REVERSAL_RISK, DATA_QUALITY, or XAU_MACRO_RISK.
- TRANSITION remains conservative: require confidence >= the supplied transition minimum; TRANSITION_WEAK is a valid WAIT category.
- Never invent a blocker. Name the exact supplied evidence in reason.
"""

INSTRUCTIONS="""You are ASTRA TRADER's final crypto trade decision engine.
Trade only BTC, ETH, GRAM, or XAU. Return exactly one JSON object.

MANDATORY DECISION PROCESS:
1) 4H = market regime. Never fight a clearly opposite 4H regime.
2) 1H = setup. Require a coherent trend/structure setup and a logical invalidation.
3) 15M = trigger. Do not enter until the trigger actually confirms.
4) Avoid chasing. Do not SHORT after an exhausted selloff or LONG after an exhausted pump.
5) Prefer pullback/retest entries and clean trend continuation over impulse chasing.
6) News is context, not an automatic BUY/SELL instruction.
7) Apply the FINAL DECISION CALIBRATION POLICY below after the deterministic gate has passed.
8) If model_gate.mtf.mode is TRANSITION: 4H must be MIXED rather than opposite.
   Treat it as a lower-risk early-regime setup. Only return LONG/SHORT when the 1H setup
   and strong 15M trigger are clean, the entry is not chased, reward/risk is strong,
   and your confidence is at least the supplied transition minimum. Otherwise WAIT.
9) For XAU only: treat Fed/BLS/BEA macro news and U.S. Treasury yields as first-class context.
   Do not infer DXY if it is unavailable. A macro headline alone is not an entry;
   require the 4H -> 1H -> 15M price confirmation supplied by the system.

The deterministic Python MTF gate, anti-chase rules, portfolio guards, Risk Engine,
and execution-quality FOK guard have authority over you. Never override them.

Never size a position. Never choose position notional.
Confidence is analytical confidence 0-100, NOT win probability.
Leverage is ultimately chosen by the deterministic Risk Engine, not by you.

ENTRY PRICE RULE:
When market.perp_okx.last_price is available, use that OKX perpetual price as the
tradable entry reference. Do not anchor entry to a spot price when the swap price differs.
The Python execution layer will re-check the live OKX price and may cancel the trade if
R:R or allowed fill quality deteriorates.

Required JSON keys:
asset, action, entry, stop_loss, take_profit_1, take_profit_2,
confidence, data_quality, volatility_regime, setup_type, reason,
wait_category, wait_is_hard_blocker.

action: LONG | SHORT | WAIT.
setup_type examples: PULLBACK_CONTINUATION, BREAKOUT_RETEST, TREND_CONTINUATION, NONE.

WAIT categories:
NONE | CHASE_RISK | STRUCTURE_CONFLICT | NEWS_RISK | VOLATILITY_RISK |
RR_OR_STOP_INVALID | REVERSAL_RISK | DATA_QUALITY | XAU_MACRO_RISK | TRANSITION_WEAK.

For LONG/SHORT: wait_category must be NONE and wait_is_hard_blocker=false.
For WAIT: entry/stop/take profits must be null. wait_category must identify the concrete blocker.
For NORMAL mode, wait_is_hard_blocker must be true for WAIT.

For LONG: stop < entry < TP1 < TP2.
For SHORT: stop > entry > TP1 > TP2.
Do not invent unavailable data.

""" + DECISION_POLICY


def extract(text):
    try:return json.loads(text)
    except:
        m=re.search(r"\{.*\}",text,re.S)
        if not m:raise ValueError("Model did not return JSON")
        return json.loads(m.group(0))

def _compact(p):
    dc=p.get("decision_context",{})
    m=dc.get("market",{})
    n=dc.get("news",{})
    ev=[]
    for e in n.get("events",[])[:config.MAX_MODEL_NEWS_EVENTS]:
        ev.append({k:e.get(k) for k in (
            "id","source","verification_status","published_at_utc",
            "title","event_type","impact_hint","trade_usable"
        )})
    return {
        "asset":p.get("asset"),
        "timeframe":p.get("timeframe"),
        "execution_mode":p.get("execution_mode"),
        "account_state":p.get("account_state"),
        "guards":p.get("guards"),
        "model_gate":p.get("model_gate"),
        "decision_policy":{
            "version":"normal_cal_v1",
            "normal_min_trade_confidence":config.MIN_TRADE_CONFIDENCE,
            "transition_min_trade_confidence":config.MTF_TRANSITION_MIN_CONFIDENCE,
            "xau_min_trade_confidence":config.XAU_MIN_TRADE_CONFIDENCE,
            "normal_wait_requires_hard_blocker":True,
        },
        "market":{
            "generated_at_utc":m.get("generated_at_utc"),
            "spot":m.get("spot"),
            "multi_timeframe":m.get("multi_timeframe"),
            "perp_okx":m.get("perp_okx"),
            "gold_macro":m.get("gold_macro"),
            "data_quality":m.get("data_quality"),
        },
        "news":{
            "summary":n.get("summary"),
            "guard":n.get("guard"),
            "events":ev,
        },
    }

def _log_usage(r,asset):
    u=getattr(r,"usage",None)
    if not u:return
    row={
        "timestamp_utc":datetime.now(timezone.utc).isoformat(),
        "asset":asset,
        "model":config.OPENAI_MODEL,
        "input_tokens":getattr(u,"input_tokens",None),
        "output_tokens":getattr(u,"output_tokens",None),
        "total_tokens":getattr(u,"total_tokens",None),
    }
    try:
        path=Path(config.STATE_DIR)/"openai_usage.jsonl"
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open("a",encoding="utf-8") as f:
            f.write(json.dumps(row,ensure_ascii=False)+"\n")
    except Exception:
        pass

ALLOWED_WAIT_CATEGORIES={
    "NONE","CHASE_RISK","STRUCTURE_CONFLICT","NEWS_RISK","VOLATILITY_RISK",
    "RR_OR_STOP_INVALID","REVERSAL_RISK","DATA_QUALITY","XAU_MACRO_RISK","TRANSITION_WEAK"
}

def _normalize_decision(d, package):
    try:
        c=float(d.get("confidence",0))
        d["confidence"]=max(0,min(100,c*100 if 0<=c<=1 else c))
    except Exception:
        d["confidence"]=0.0

    a=str(d.get("action","WAIT")).upper()
    d["action"]=a if a in {"LONG","SHORT","WAIT"} else "WAIT"
    d["asset"]=str(d.get("asset",package.get("asset",""))).upper()
    d["timeframe"]=d.get("timeframe") or package.get("timeframe") or config.TRADING_TIMEFRAME
    d["setup_type"]=str(d.get("setup_type","NONE")).upper()
    d["decision_policy_version"]="normal_cal_v1"

    cat=str(d.get("wait_category") or "NONE").upper().strip()
    if cat not in ALLOWED_WAIT_CATEGORIES:
        cat="UNSPECIFIED"

    if d["action"]=="WAIT":
        d["entry"]=None
        d["stop_loss"]=None
        d["take_profit_1"]=None
        d["take_profit_2"]=None
        if not d.get("setup_type"):
            d["setup_type"]="NONE"
        d["wait_category"]=cat if cat!="NONE" else "UNSPECIFIED"
        d["wait_is_hard_blocker"]=bool(d.get("wait_is_hard_blocker",False))
    else:
        d["wait_category"]="NONE"
        d["wait_is_hard_blocker"]=False

    return d

def decide(package):
    client=OpenAI()
    compact=_compact(package)
    kwargs={
        "input":"Apply this final decision calibration policy exactly:\n"+DECISION_POLICY+
                "\nAnalyze this multi-timeframe pre-filtered trading context and return the required JSON only:\n"+
                json.dumps(compact,ensure_ascii=False,separators=(",",":")),
        "store":False,
    }
    if config.OPENAI_PROMPT_ID:
        kwargs["prompt"]={"id":config.OPENAI_PROMPT_ID}
    else:
        kwargs["model"]=config.OPENAI_MODEL
        kwargs["instructions"]=INSTRUCTIONS
        kwargs["reasoning"]={"effort":config.OPENAI_REASONING_EFFORT}

    r=client.responses.create(**kwargs)
    _log_usage(r,package.get("asset"))
    d=extract(r.output_text)
    return _normalize_decision(d, package)

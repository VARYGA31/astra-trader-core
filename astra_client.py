import json,re
from pathlib import Path
from datetime import datetime,timezone
from openai import OpenAI
import config

INSTRUCTIONS="""You are ASTRA TRADER's final crypto trade decision engine.
Trade only BTC, ETH, or GRAM. Return exactly one JSON object.

MANDATORY DECISION PROCESS:
1) 4H = market regime. Never fight a clearly opposite 4H regime.
2) 1H = setup. Require a coherent trend/structure setup and a logical invalidation.
3) 15M = trigger. Do not enter until the trigger actually confirms.
4) Avoid chasing. Do not SHORT after an exhausted selloff or LONG after an exhausted pump.
5) Prefer pullback/retest entries and clean trend continuation over impulse chasing.
6) News is context, not an automatic BUY/SELL instruction.
7) If the setup is unclear, late, crowded, contradictory, or has poor reward/risk: WAIT.

The deterministic Python MTF gate, anti-chase rules, portfolio guards, and Risk Engine
have authority over you. Never override them.

Never size a position. Never choose position notional.
Confidence is analytical confidence 0-100, NOT win probability.
Leverage is ultimately chosen by the deterministic Risk Engine, not by you.

Required JSON keys:
asset, action, entry, stop_loss, take_profit_1, take_profit_2,
confidence, data_quality, volatility_regime, setup_type, reason.

action: LONG | SHORT | WAIT.
setup_type examples: PULLBACK_CONTINUATION, BREAKOUT_RETEST, TREND_CONTINUATION, NONE.
For WAIT: entry/stop/take profits must be null and setup_type may be NONE.

For LONG: stop < entry < TP1 < TP2.
For SHORT: stop > entry > TP1 > TP2.
Do not invent unavailable data.
"""

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
        "market":{
            "generated_at_utc":m.get("generated_at_utc"),
            "spot":m.get("spot"),
            "multi_timeframe":m.get("multi_timeframe"),
            "perp_okx":m.get("perp_okx"),
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

def decide(package):
    client=OpenAI()
    compact=_compact(package)
    kwargs={
        "input":"Analyze this multi-timeframe pre-filtered trading context and return the required JSON only:\n"+
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

    if d["action"]=="WAIT":
        d["entry"]=None
        d["stop_loss"]=None
        d["take_profit_1"]=None
        d["take_profit_2"]=None
        if not d.get("setup_type"):
            d["setup_type"]="NONE"
    return d

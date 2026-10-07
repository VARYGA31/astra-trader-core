import json,re
from openai import OpenAI
import config

INSTRUCTIONS="""You are ASTRA TRADER's decision engine.
Trade only BTC, ETH, or GRAM. Return exactly one JSON object.
If data is missing, stale, failed, or critical high-impact news is unresolved, action must be WAIT.
Never size a position. Risk Engine owns sizing.
Required keys: asset, action, entry, stop_loss, take_profit_1, take_profit_2, confidence,
data_quality, volatility_regime, leverage, reason.
For WAIT, entry/stop/take profits must be null.
confidence is analytical confidence, not win probability.
Prefer leverage 3; 4-5 only for unusually strong conditions and never to increase maximum loss.
"""

def extract(text):
    try:return json.loads(text)
    except:
        m=re.search(r"\{.*\}",text,re.S)
        if not m:raise ValueError("Model did not return JSON")
        return json.loads(m.group(0))

def decide(package):
    client=OpenAI()
    kwargs={"input":"Analyze this trading context and return the required JSON only:\n"+json.dumps(package,ensure_ascii=False,separators=(",",":")),
            "store":False}
    if config.OPENAI_PROMPT_ID:
        kwargs["prompt"]={"id":config.OPENAI_PROMPT_ID}
    else:
        kwargs["model"]=config.OPENAI_MODEL
        kwargs["instructions"]=INSTRUCTIONS
        kwargs["reasoning"]={"effort":config.OPENAI_REASONING_EFFORT}
    r=client.responses.create(**kwargs)
    decision = extract(r.output_text)

    # Normalize model output before it reaches the deterministic Risk Engine.
    confidence = decision.get("confidence")
    try:
        if confidence is not None:
            confidence = float(confidence)
            if 0 <= confidence <= 1:
                confidence *= 100.0
            decision["confidence"] = max(0.0, min(100.0, confidence))
    except Exception:
        decision["confidence"] = 0.0

    action = str(decision.get("action", "WAIT")).upper()
    if action not in {"LONG", "SHORT", "WAIT"}:
        action = "WAIT"
    decision["action"] = action
    decision["asset"] = str(decision.get("asset", package.get("asset", ""))).upper()
    decision["timeframe"] = decision.get("timeframe") or package.get("timeframe") or config.TRADING_TIMEFRAME

    if action == "WAIT":
        decision["entry"] = None
        decision["stop_loss"] = None
        decision["take_profit_1"] = None
        decision["take_profit_2"] = None

    return decision

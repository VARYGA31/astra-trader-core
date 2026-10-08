#!/usr/bin/env python3
import json
from openai import OpenAI
import config

INSTRUCTIONS = """You are ASTRA TRADER's emergency position-risk reviewer.
You are NOT opening a trade. You are deciding whether an already-open crypto position
should be closed immediately because a NEW, VERIFIED, HIGH-impact news event conflicts
with the position.

Return exactly one JSON object:
{
  "action": "CLOSE_NOW" or "HOLD",
  "confidence": 0-100,
  "reason": "short explanation"
}

Rules:
- CLOSE_NOW only when the verified event materially invalidates or strongly opposes the
  current LONG/SHORT thesis and waiting for the normal stop is clearly inferior.
- Do not close merely because a headline sounds dramatic.
- Consider whether the event is already priced in and the current market reaction.
- If ambiguous, stale, weakly related, or not genuinely opposite: HOLD.
- Never reverse the position here. Only CLOSE_NOW or HOLD.
"""

def decide_news_exit(position, event, market):
    client = OpenAI()
    compact_market = {
        "spot": market.get("spot", {}),
        "perp_okx": market.get("perp_okx", {}),
        "data_quality": market.get("data_quality", {}),
    }
    payload = {
        "position": position,
        "event": {
            "asset": event.get("asset"),
            "source": event.get("source"),
            "verification_status": event.get("verification_status"),
            "published_at_utc": event.get("published_at_utc"),
            "title": event.get("title"),
            "summary": event.get("summary"),
            "event_type": event.get("event_type"),
            "impact_hint": event.get("impact_hint"),
            "trade_usable": event.get("trade_usable"),
            "corroborated_by": event.get("corroborated_by"),
        },
        "market": compact_market,
    }
    r = client.responses.create(
        model=config.OPENAI_MODEL,
        instructions=INSTRUCTIONS,
        input=json.dumps(payload, ensure_ascii=False, separators=(",",":")),
        reasoning={"effort":"low"},
        store=False,
    )
    try:
        out = json.loads(r.output_text)
    except Exception:
        out = {"action":"HOLD","confidence":0,"reason":"INVALID_MODEL_JSON"}

    action = str(out.get("action","HOLD")).upper()
    if action not in {"CLOSE_NOW","HOLD"}:
        action = "HOLD"
    try:
        conf = float(out.get("confidence",0))
        if 0 <= conf <= 1:
            conf *= 100
    except Exception:
        conf = 0

    return {
        "action":action,
        "confidence":max(0.0,min(100.0,conf)),
        "reason":str(out.get("reason","")),
        "usage":{
            "input_tokens":getattr(getattr(r,"usage",None),"input_tokens",None),
            "output_tokens":getattr(getattr(r,"usage",None),"output_tokens",None),
            "total_tokens":getattr(getattr(r,"usage",None),"total_tokens",None),
        },
    }

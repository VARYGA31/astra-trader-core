#!/usr/bin/env python3
import json
from openai import OpenAI
import config
import model_budget

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
    asset=str((position or {}).get("asset") or (event or {}).get("asset") or "").upper()
    permit=model_budget.before_call(
        "EMERGENCY_NEWS_EXIT",
        asset=asset,
        priority="emergency",
        model=config.OPENAI_MODEL,
    )
    if not permit.get("allowed"):
        return {
            "action":"HOLD",
            "confidence":0.0,
            "reason":permit.get("reason") or "MODEL_BUDGET_BLOCK",
            "model_called":False,
            "model_budget":model_budget.summary(),
        }

    reservation=permit.get("reservation_id")
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
    try:
        r = client.responses.create(
            model=config.OPENAI_MODEL,
            instructions=INSTRUCTIONS,
            input=json.dumps(payload, ensure_ascii=False, separators=(",",":")),
            reasoning={"effort":"low"},
            max_output_tokens=int(config.MODEL_EXIT_MAX_OUTPUT_TOKENS),
            store=False,
        )
    except Exception as e:
        info=model_budget.record_error(
            e,reservation,"EMERGENCY_NEWS_EXIT",asset=asset,model=config.OPENAI_MODEL
        )
        return {
            "action":"HOLD",
            "confidence":0.0,
            "reason":f"MODEL_API_{info.get('kind') or 'ERROR'}",
            "model_called":False,
            "model_api_error":info,
            "model_budget":model_budget.summary(),
        }

    model_budget.record_success(
        r,reservation,"EMERGENCY_NEWS_EXIT",asset=asset,
        strategy_mode="EMERGENCY",model=config.OPENAI_MODEL,
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
        "model_called":True,
        "usage":{
            "input_tokens":getattr(getattr(r,"usage",None),"input_tokens",None),
            "output_tokens":getattr(getattr(r,"usage",None),"output_tokens",None),
            "total_tokens":getattr(getattr(r,"usage",None),"total_tokens",None),
        },
        "model_budget":model_budget.summary(),
    }

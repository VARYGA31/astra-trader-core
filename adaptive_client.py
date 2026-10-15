#!/usr/bin/env python3
"""Multi-asset strategist for ASTRA ADAPTIVE v1.

One model call ranks the allowed crypto assets together. Python remains the
independent safety/risk/execution authority.
"""
import json,re
from datetime import datetime,timezone
from pathlib import Path

from openai import OpenAI

import config
import adaptive_memory

INSTRUCTIONS = """You are ASTRA ADAPTIVE v1, a multi-asset trading strategist.

Analyze BTC, ETH and GRAM together and choose at most ONE best opportunity.
You may choose NORMAL, SCALP, or WAIT. NORMAL means a multi-hour trade. SCALP
means roughly 5-60 minutes. You are not forced to trade.

You receive raw/derived market evidence, news, guards and selected similar
historical outcomes from ASTRA's own external memory. Treat historical outcomes
as examples, not guarantees.

IMPORTANT:
- Python Safety/Risk/Execution has final authority and can reject your idea.
- Never size position notional and never choose account risk.
- Do not copy social sentiment or outside traders blindly.
- Confidence is analytical confidence 0-100, not win probability.
- Use OKX perpetual last_price as entry reference when available.
- Prefer a trade when evidence is coherent and reward/risk is realistic; do
  not demand perfect alignment across every indicator.
- WAIT when there is no clear asymmetric opportunity or there is a concrete
  safety/market invalidator.
- Never invent unavailable data.

Return exactly one JSON object with:
{
  "market_summary": "brief",
  "assets": [
    {
      "asset":"BTC|ETH|GRAM",
      "score":0-100,
      "bias":"LONG|SHORT|NEUTRAL",
      "preferred_strategy":"NORMAL|SCALP|WAIT",
      "actionable":true|false,
      "confidence":0-100,
      "reason":"brief evidence-based explanation"
    }
  ],
  "best_opportunity":{
    "asset":"BTC|ETH|GRAM|null",
    "action":"LONG|SHORT|WAIT",
    "strategy":"NORMAL|SCALP|WAIT",
    "scalp_tier":"PRIME|FAST|null",
    "setup_quality":0-100,
    "confidence":0-100,
    "entry":number|null,
    "stop_loss":number|null,
    "take_profit_1":number|null,
    "take_profit_2":number|null,
    "time_horizon_minutes":number|null,
    "setup_type":"string",
    "volatility_regime":"LOW|NORMAL|ELEVATED|HIGH|EXTREME",
    "reason":"brief concrete rationale"
  }
}

For LONG require stop < entry < TP1 < TP2.
For SHORT require stop > entry > TP1 > TP2.
For WAIT all price levels must be null.
For SCALP use FAST unless the setup is exceptionally clean and strong enough
to justify PRIME. Python will independently enforce confidence, quality, stop,
R:R, spread, slippage, exposure and drawdown constraints.
"""

def _extract(text):
    try:
        return json.loads(text)
    except Exception:
        m=re.search(r"\{.*\}",str(text or ""),re.S)
        if not m:
            raise ValueError("Adaptive model did not return JSON")
        return json.loads(m.group(0))

def _compact_package(p):
    dc=(p or {}).get("decision_context",{})
    m=dc.get("market",{})
    n=dc.get("news",{})
    frames=(m.get("multi_timeframe") or {}).get("frames",{})
    keep={}
    for tf in ("5m","15m","1h","4h"):
        x=frames.get(tf) or {}
        keep[tf]={
            "status":x.get("status"),
            "last_confirmed_close_time_ms":x.get("last_confirmed_close_time_ms"),
            "close":x.get("close"),
            "changes_pct":x.get("changes_pct"),
            "indicators":x.get("indicators"),
            "regimes":x.get("regimes"),
            "structure":x.get("structure"),
            "volume":x.get("volume"),
            "last_candle":x.get("last_candle"),
        }
    events=[]
    for e in (n.get("events") or [])[:config.MAX_MODEL_NEWS_EVENTS]:
        events.append({k:e.get(k) for k in (
            "id","source","verification_status","published_at_utc","title",
            "event_type","impact_hint","trade_usable"
        )})
    spot=m.get("spot") or {}
    perp=m.get("perp_okx") or {}
    return {
        "asset":p.get("asset"),
        "guards":p.get("guards"),
        "account_state":p.get("account_state"),
        "market":{
            "generated_at_utc":m.get("generated_at_utc"),
            "spot":{
                "price":spot.get("price"),
                "ticker_24h":spot.get("ticker_24h"),
                "changes_pct":spot.get("changes_pct"),
                "indicators":spot.get("indicators"),
                "regimes":spot.get("regimes"),
                "order_book":spot.get("order_book"),
                "trade_flow":spot.get("trade_flow"),
            },
            "perp_okx":{
                "last_price":perp.get("last_price"),
                "bid_price":perp.get("bid_price"),
                "ask_price":perp.get("ask_price"),
                "funding_rate":perp.get("funding_rate"),
                "open_interest":perp.get("open_interest"),
                "open_interest_contracts":perp.get("open_interest_contracts"),
            },
            "frames":keep,
            "data_quality":m.get("data_quality"),
        },
        "news":{
            "summary":n.get("summary"),
            "guard":n.get("guard"),
            "events":events,
        },
    }

def _log_usage(r):
    u=getattr(r,"usage",None)
    if not u:
        return
    row={
        "timestamp_utc":datetime.now(timezone.utc).isoformat(),
        "asset":"MULTI",
        "strategy_mode":"AUTO",
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

def _clamp(v,lo=0.0,hi=100.0):
    try:
        x=float(v)
        if 0<=x<=1:
            x*=100
        return max(lo,min(hi,x))
    except Exception:
        return 0.0

def normalize(d, packages):
    d=d if isinstance(d,dict) else {}
    allowed=set(packages)
    assets=[]
    seen=set()
    for x in d.get("assets") or []:
        if not isinstance(x,dict):
            continue
        asset=str(x.get("asset") or "").upper()
        if asset not in allowed or asset in seen:
            continue
        seen.add(asset)
        bias=str(x.get("bias") or "NEUTRAL").upper()
        if bias not in {"LONG","SHORT","NEUTRAL"}:
            bias="NEUTRAL"
        strategy=str(x.get("preferred_strategy") or "WAIT").upper()
        if strategy not in {"NORMAL","SCALP","WAIT"}:
            strategy="WAIT"
        assets.append({
            "asset":asset,
            "score":_clamp(x.get("score")),
            "bias":bias,
            "preferred_strategy":strategy,
            "actionable":bool(x.get("actionable",False)),
            "confidence":_clamp(x.get("confidence")),
            "reason":str(x.get("reason") or "")[:800],
        })
    for asset in sorted(allowed-seen):
        assets.append({
            "asset":asset,"score":0.0,"bias":"NEUTRAL",
            "preferred_strategy":"WAIT","actionable":False,
            "confidence":0.0,"reason":"No model opinion returned."
        })

    best=d.get("best_opportunity") or {}
    action=str(best.get("action") or "WAIT").upper()
    if action not in {"LONG","SHORT","WAIT"}:
        action="WAIT"
    asset=str(best.get("asset") or "").upper()
    strategy=str(best.get("strategy") or "WAIT").upper()
    if strategy not in {"NORMAL","SCALP","WAIT"}:
        strategy="WAIT"
    if asset not in allowed:
        action="WAIT"; asset=""; strategy="WAIT"

    tier=str(best.get("scalp_tier") or "FAST").upper()
    if tier not in {"PRIME","FAST"}:
        tier="FAST"

    out_best={
        "asset":asset or None,
        "action":action,
        "strategy":strategy if action!="WAIT" else "WAIT",
        "scalp_tier":tier if action!="WAIT" and strategy=="SCALP" else None,
        "setup_quality":_clamp(best.get("setup_quality")),
        "confidence":_clamp(best.get("confidence")),
        "entry":best.get("entry"),
        "stop_loss":best.get("stop_loss"),
        "take_profit_1":best.get("take_profit_1"),
        "take_profit_2":best.get("take_profit_2"),
        "time_horizon_minutes":best.get("time_horizon_minutes"),
        "setup_type":str(best.get("setup_type") or "ADAPTIVE"),
        "volatility_regime":str(best.get("volatility_regime") or "NORMAL").upper(),
        "reason":str(best.get("reason") or "")[:1200],
    }
    if action=="WAIT":
        for k in ("entry","stop_loss","take_profit_1","take_profit_2","time_horizon_minutes"):
            out_best[k]=None

    return {
        "timestamp_utc":datetime.now(timezone.utc).isoformat(),
        "cycle_id":datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ"),
        "policy_version":"adaptive_v1",
        "market_summary":str(d.get("market_summary") or "")[:1200],
        "assets":assets,
        "best_opportunity":out_best,
    }

def decide_market(packages):
    compact={a:_compact_package(p) for a,p in packages.items()}
    memory=adaptive_memory.similar_cases(packages,config.ADAPTIVE_MEMORY_EXAMPLES)
    payload={
        "execution_mode":config.EXECUTION_MODE,
        "allowed_assets":list(packages),
        "safety_note":"Python independently validates every actual order.",
        "markets":compact,
        "similar_historical_outcomes":memory,
    }
    kwargs={
        "input":"Analyze the multi-asset package and return the required JSON only:\n"+
                json.dumps(payload,ensure_ascii=False,separators=(",",":")),
        "store":False,
    }
    if config.OPENAI_PROMPT_ID:
        kwargs["prompt"]={"id":config.OPENAI_PROMPT_ID}
    else:
        kwargs["model"]=config.OPENAI_MODEL
        kwargs["instructions"]=INSTRUCTIONS
        kwargs["reasoning"]={"effort":config.OPENAI_REASONING_EFFORT}
    r=OpenAI().responses.create(**kwargs)
    _log_usage(r)
    return normalize(_extract(r.output_text),packages)

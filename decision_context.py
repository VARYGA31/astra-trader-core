#!/usr/bin/env python3
import sys
import json
import subprocess
from datetime import datetime, timezone

ALLOWED = {"BTC", "ETH", "GRAM"}

def run_json(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        return {
            "_status": "FAILED",
            "_stderr": p.stderr.strip()[:2000],
            "_stdout": p.stdout.strip()[:2000],
            "_returncode": p.returncode,
        }
    try:
        return json.loads(p.stdout)
    except Exception as e:
        return {
            "_status": "FAILED",
            "_error": f"JSONDecodeError: {e}",
            "_stdout": p.stdout.strip()[:2000],
        }

def now_utc():
    return datetime.now(timezone.utc).isoformat()

asset = (sys.argv[1] if len(sys.argv) > 1 else "BTC").upper()
lookback_hours = int(sys.argv[2]) if len(sys.argv) > 2 else 12

if asset not in ALLOWED:
    print(json.dumps({
        "status": "TRADE_NOT_ALLOWED",
        "requested_asset": asset,
        "allowed_assets": sorted(ALLOWED),
    }, ensure_ascii=False))
    raise SystemExit(2)

market = run_json(["python", "/workspace/market_snapshot.py", asset])
news = run_json(["python", "/workspace/news_snapshot.py", asset, str(lookback_hours)])

high_impact = []
primary = []
if isinstance(news, dict):
    for e in news.get("events", []):
        if e.get("impact_hint") == "HIGH":
            high_impact.append(e)
        if e.get("verification_status") == "PRIMARY":
            primary.append(e)

market_quality = None
if isinstance(market, dict):
    market_quality = market.get("data_quality", {}).get("status")

news_count = 0
if isinstance(news, dict):
    news_count = news.get("summary", {}).get("events_returned", 0)

context = {
    "asset": asset,
    "generated_at_utc": now_utc(),
    "lookback_hours": lookback_hours,
    "allowed_trading_assets": ["BTC", "ETH", "GRAM"],
    "market": market,
    "news": {
        "summary": news.get("summary", {}) if isinstance(news, dict) else {},
        "high_impact_events": high_impact[:10],
        "primary_events": primary[:10],
        "all_events": news.get("events", [])[:20] if isinstance(news, dict) else [],
    },
    "decision_guardrails": {
        "trade_allowed": asset in ALLOWED,
        "require_market_data": True,
        "require_news_verification_for_high_impact_non_primary": True,
        "no_trade_if_market_data_failed": True,
        "no_trade_if_critical_news_unverified": True,
        "no_order_execution_in_this_script": True,
    },
    "context_quality": {
        "market_data_status": market_quality,
        "news_events_count": news_count,
        "high_impact_events_count": len(high_impact),
        "primary_events_count": len(primary),
    },
}

print(json.dumps(context, ensure_ascii=False, separators=(",", ":")))

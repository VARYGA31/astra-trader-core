#!/usr/bin/env python3
import sys, json, re, html
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus

import feedparser

ALLOWED = {"BTC", "ETH", "GRAM"}

ALIASES = {
    "BTC": [
        "bitcoin", "btc", "bitcoin etf", "spot bitcoin", "bitcoin core",
    ],
    "ETH": [
        "ethereum", "ether", "eth", "ethereum foundation", "ethereum etf",
        "staking", "validator", "pectra", "glamsterdam",
    ],
    "GRAM": [
        "gram", "gram/usdt", "gram token",
        "ton", "toncoin", "the open network",
        "telegram wallet", "telegram mini app", "telegram mini apps",
        "ton foundation", "ton blockchain",
    ],
}

# TIER 0/1 = highest trust / primary or major institutional sources.
# TIER 2 = high-quality crypto media used for confirmation/context.
BASE_FEEDS = [
    {
        "name": "Federal Reserve",
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "tier": 0,
        "kind": "official_macro",
        "primary": True,
    },
    {
        "name": "SEC",
        "url": "https://www.sec.gov/news/pressreleases.rss",
        "tier": 0,
        "kind": "official_regulator",
        "primary": True,
    },
    {
        "name": "Ethereum Foundation Blog",
        "url": "https://blog.ethereum.org/en/feed.xml",
        "tier": 0,
        "kind": "official_project",
        "primary": True,
    },
    {
        "name": "Coinbase Blog",
        "url": "https://www.coinbase.com/blog/rss.xml",
        "tier": 1,
        "kind": "official_exchange",
        "primary": True,
    },
    {
        "name": "CoinDesk",
        "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "tier": 2,
        "kind": "crypto_media",
        "primary": False,
    },
    {
        "name": "The Block",
        "url": "https://www.theblock.co/rss.xml",
        "tier": 2,
        "kind": "crypto_media",
        "primary": False,
    },
    {
        "name": "Decrypt",
        "url": "https://decrypt.co/feed",
        "tier": 2,
        "kind": "crypto_media",
        "primary": False,
    },
]

# Discovery-only feeds. These are NOT treated as verified primary sources.
# Their purpose is to surface fast-moving items that ASTRA must verify
# against the named original domain before acting on them.
DISCOVERY_QUERIES = {
    "BTC": [
        'site:reuters.com bitcoin OR BTC',
        'site:binance.com bitcoin announcement',
    ],
    "ETH": [
        'site:reuters.com ethereum OR ether OR ETH',
        'site:binance.com ethereum announcement',
    ],
    "GRAM": [
        'site:ton.org GRAM OR TON OR "The Open Network"',
        'site:telegram.org GRAM OR TON OR wallet',
        'site:binance.com GRAM announcement',
        'site:reuters.com TON OR GRAM OR Telegram crypto',
    ],
}

EVENT_RULES = [
    ("REGULATION", ["sec", "cftc", "regulation", "regulator", "lawsuit", "enforcement", "approval", "etf"]),
    ("MACRO", ["federal reserve", "fed ", "rate cut", "rate hike", "inflation", "cpi", "jobs", "employment", "treasury"]),
    ("SECURITY", ["hack", "exploit", "breach", "vulnerability", "stolen", "attack"]),
    ("EXCHANGE", ["binance", "coinbase", "okx", "bybit", "listing", "delisting", "deposit", "withdrawal"]),
    ("PROTOCOL", ["upgrade", "fork", "testnet", "mainnet", "validator", "staking", "protocol"]),
    ("TELEGRAM_TON", ["telegram", "ton", "toncoin", "the open network", "gram"]),
    ("ETF", ["etf", "exchange-traded fund"]),
]

HIGH_IMPACT_WORDS = [
    "approved", "approval", "rejected", "ban", "banned", "halt",
    "suspend", "suspended", "hack", "exploit", "outage", "emergency",
    "listing", "delisting", "rate cut", "rate hike", "etf",
]

def now_utc():
    return datetime.now(timezone.utc)

def clean_text(s):
    s = html.unescape(s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def parse_time(entry):
    for key in ("published_parsed", "updated_parsed"):
        v = entry.get(key)
        if v:
            try:
                return datetime(*v[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None

def relevant(asset, title, summary):
    text = f"{title} {summary}".lower()
    return any(term.lower() in text for term in ALIASES[asset])

def event_type(title, summary):
    text = f"{title} {summary}".lower()
    scores = []
    for label, words in EVENT_RULES:
        score = sum(1 for w in words if w in text)
        if score:
            scores.append((score, label))
    return max(scores)[1] if scores else "GENERAL"

def impact_hint(title, summary, tier):
    text = f"{title} {summary}".lower()
    hits = sum(1 for w in HIGH_IMPACT_WORDS if w in text)
    if tier == 0 and hits >= 1:
        return "HIGH"
    if hits >= 2:
        return "HIGH"
    if hits == 1:
        return "MEDIUM"
    return "LOW"

def fetch_feed(source, asset, cutoff):
    parsed = feedparser.parse(source["url"])
    events = []
    for e in parsed.entries[:50]:
        title = clean_text(e.get("title", ""))
        summary = clean_text(e.get("summary", e.get("description", "")))
        if not relevant(asset, title, summary):
            continue
        dt = parse_time(e)
        if dt and dt < cutoff:
            continue
        link = e.get("link", "")
        events.append({
            "asset": asset,
            "source": source["name"],
            "source_tier": source["tier"],
            "source_kind": source["kind"],
            "primary_source": source["primary"],
            "verification_status": "PRIMARY" if source["primary"] else "REQUIRES_CONFIRMATION",
            "published_at_utc": dt.isoformat() if dt else None,
            "title": title,
            "summary": summary[:1200],
            "url": link,
            "event_type": event_type(title, summary),
            "impact_hint": impact_hint(title, summary, source["tier"]),
        })
    return events, {
        "source": source["name"],
        "url": source["url"],
        "bozo": bool(getattr(parsed, "bozo", False)),
        "entries_seen": len(parsed.entries),
    }

def google_news_feed(query):
    return (
        "https://news.google.com/rss/search?q="
        + quote_plus(query)
        + "&hl=en-US&gl=US&ceid=US:en"
    )

def fetch_discovery(asset, cutoff):
    events, states = [], []
    for query in DISCOVERY_QUERIES.get(asset, []):
        src = {
            "name": f"Discovery: {query}",
            "url": google_news_feed(query),
            "tier": 3,
            "kind": "discovery",
            "primary": False,
        }
        evs, state = fetch_feed(src, asset, cutoff)
        for ev in evs:
            ev["verification_status"] = "DISCOVERY_ONLY"
        events.extend(evs)
        states.append(state)
    return events, states

def dedupe(events):
    seen = set()
    out = []
    for e in events:
        key = (e.get("url") or "", e.get("title","").lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out

def sort_key(e):
    ts = e.get("published_at_utc") or ""
    # Lower tier = more trusted. Newer first inside trust level.
    return (e.get("source_tier", 99), "" if not ts else ts)

def main():
    asset = (sys.argv[1] if len(sys.argv) > 1 else "BTC").upper()
    hours = int(sys.argv[2]) if len(sys.argv) > 2 else 12

    if asset not in ALLOWED:
        print(json.dumps({
            "status": "TRADE_NOT_ALLOWED",
            "allowed_assets": sorted(ALLOWED),
            "requested_asset": asset,
        }, ensure_ascii=False))
        raise SystemExit(2)

    cutoff = now_utc() - timedelta(hours=hours)
    events = []
    source_states = []

    for src in BASE_FEEDS:
        try:
            evs, state = fetch_feed(src, asset, cutoff)
            events.extend(evs)
            source_states.append(state)
        except Exception as ex:
            source_states.append({
                "source": src["name"],
                "url": src["url"],
                "error": f"{type(ex).__name__}: {ex}",
            })

    try:
        evs, states = fetch_discovery(asset, cutoff)
        events.extend(evs)
        source_states.extend(states)
    except Exception as ex:
        source_states.append({"source": "discovery", "error": f"{type(ex).__name__}: {ex}"})

    events = dedupe(events)

    # Trust first, then newest within each tier.
    events.sort(
        key=lambda e: (
            e.get("source_tier", 99),
            -(datetime.fromisoformat(e["published_at_utc"]).timestamp()
              if e.get("published_at_utc") else 0)
        )
    )

    # Keep output compact to reduce model tokens.
    events = events[:30]

    primary_count = sum(1 for e in events if e["verification_status"] == "PRIMARY")
    high_impact = sum(1 for e in events if e["impact_hint"] == "HIGH")

    result = {
        "asset": asset,
        "generated_at_utc": now_utc().isoformat(),
        "lookback_hours": hours,
        "allowed_trading_assets": ["BTC", "ETH", "GRAM"],
        "events": events,
        "summary": {
            "events_returned": len(events),
            "primary_events": primary_count,
            "high_impact_events": high_impact,
        },
        "policy": {
            "tier_0_1": "Primary/official sources. Highest trust.",
            "tier_2": "High-quality crypto media. Confirm important claims with primary source.",
            "tier_3": "Discovery only. Never trade directly from this tier.",
            "rule": "Astra must verify high-impact non-primary events before using them for a trade decision."
        },
        "source_health": source_states,
    }

    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))

if __name__ == "__main__":
    main()

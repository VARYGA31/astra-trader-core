#!/usr/bin/env python3
import sys, json, statistics
from datetime import datetime, timezone
import requests

TIMEOUT = 15

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def safe_get(url, params=None):
    rec = {"url": url, "params": params or {}, "http_status": None, "ok": False,
           "error": None, "ts_utc": utc_now(), "data": None}
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
        rec["http_status"] = r.status_code
        rec["url"] = r.url
        if r.ok:
            rec["data"] = r.json()
            rec["ok"] = True
        else:
            rec["error"] = (r.text or "")[:500]
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {e}"
    return rec

def pct(a, b):
    if a in (None, 0) or b is None:
        return None
    return (b / a - 1.0) * 100.0

def classify_trend(c24, c4):
    if c24 is None or c4 is None: return "INSUFFICIENT_DATA"
    if c24 > 1 and c4 > 0: return "BULLISH"
    if c24 < -1 and c4 < 0: return "BEARISH"
    return "NEUTRAL"

def classify_book(imb):
    if imb is None: return "INSUFFICIENT_DATA"
    if imb >= 0.55: return "BID_DOMINANT"
    if imb <= 0.45: return "ASK_DOMINANT"
    return "BALANCED"

def classify_flow(buy_share):
    if buy_share is None: return "INSUFFICIENT_DATA"
    if buy_share >= 0.55: return "BUY_DOMINANT"
    if buy_share <= 0.45: return "SELL_DOMINANT"
    return "BALANCED"

asset = (sys.argv[1] if len(sys.argv) > 1 else "BTC").upper()
spot_symbol = f"{asset}USDT"
okx_swap = f"{asset}-USDT-SWAP"

BINANCE = "https://data-api.binance.vision"
OKX = "https://www.okx.com"

out = {
    "asset": asset,
    "generated_at_utc": utc_now(),
    "spot": {}, "trend": {}, "order_book": {}, "trade_flow": {},
    "derivatives": {},
    "liquidations": {
        "status": "UNAVAILABLE",
        "note": "No complete public liquidation feed is guaranteed by the selected APIs."
    },
    "sources": {}, "data_quality": {}
}

ticker = safe_get(f"{BINANCE}/api/v3/ticker/24hr", {"symbol": spot_symbol})
out["sources"]["binance_ticker_24h"] = {k:v for k,v in ticker.items() if k != "data"}
if ticker["ok"] and isinstance(ticker["data"], dict):
    d = ticker["data"]
    out["spot"] = {
        "symbol": spot_symbol,
        "price": float(d["lastPrice"]),
        "high_24h": float(d["highPrice"]),
        "low_24h": float(d["lowPrice"]),
        "volume_base_24h": float(d["volume"]),
        "volume_quote_24h": float(d["quoteVolume"]),
        "exchange_price_change_24h_pct": float(d["priceChangePercent"]),
    }

kl = safe_get(f"{BINANCE}/api/v3/klines", {"symbol": spot_symbol, "interval": "1h", "limit": 100})
out["sources"]["binance_klines_1h"] = {k:v for k,v in kl.items() if k != "data"}
if kl["ok"] and isinstance(kl["data"], list) and kl["data"]:
    closes = [float(r[4]) for r in kl["data"]]
    vols = [float(r[5]) for r in kl["data"]]
    last = closes[-1]
    c1 = pct(closes[-2], last) if len(closes) >= 2 else None
    c4 = pct(closes[-5], last) if len(closes) >= 5 else None
    c24 = pct(closes[-25], last) if len(closes) >= 25 else None
    avg24 = statistics.mean(vols[-24:]) if len(vols) >= 24 else (statistics.mean(vols) if vols else None)
    out["trend"] = {
        "candles_1h_count": len(closes),
        "change_1h_pct": c1,
        "change_4h_pct": c4,
        "change_24h_pct": c24,
        "volume_last_1h_base": vols[-1] if vols else None,
        "volume_avg_24h_base": avg24,
        "volume_last_vs_avg_ratio": (vols[-1]/avg24 if vols and avg24 else None),
        "classification": classify_trend(c24, c4),
    }

depth = safe_get(f"{BINANCE}/api/v3/depth", {"symbol": spot_symbol, "limit": 20})
out["sources"]["binance_depth_top20"] = {k:v for k,v in depth.items() if k != "data"}
if depth["ok"] and isinstance(depth["data"], dict):
    bids = [(float(p), float(q)) for p,q in depth["data"].get("bids", [])]
    asks = [(float(p), float(q)) for p,q in depth["data"].get("asks", [])]
    if bids and asks:
        bid_vol = sum(q for _,q in bids)
        ask_vol = sum(q for _,q in asks)
        total = bid_vol + ask_vol
        imb = bid_vol / total if total else None
        best_bid, best_ask = bids[0][0], asks[0][0]
        mid = (best_bid + best_ask) / 2
        out["order_book"] = {
            "best_bid": best_bid, "best_ask": best_ask,
            "spread_abs": best_ask - best_bid,
            "spread_pct": ((best_ask-best_bid)/mid*100 if mid else None),
            "bid_volume_top20": bid_vol,
            "ask_volume_top20": ask_vol,
            "imbalance": imb,
            "classification": classify_book(imb),
        }

tr = safe_get(f"{BINANCE}/api/v3/trades", {"symbol": spot_symbol, "limit": 500})
out["sources"]["binance_recent_trades"] = {k:v for k,v in tr.items() if k != "data"}
if tr["ok"] and isinstance(tr["data"], list):
    buy = sell = 0.0
    sizes = []
    for x in tr["data"]:
        q = float(x["qty"])
        sizes.append(q)
        if x.get("isBuyerMaker"):
            sell += q
        else:
            buy += q
    total = buy + sell
    buy_share = buy/total if total else None
    out["trade_flow"] = {
        "trades_count": len(tr["data"]),
        "aggressive_buy_base": buy,
        "aggressive_sell_base": sell,
        "buy_sell_ratio": (buy/sell if sell else None),
        "buy_share": buy_share,
        "sell_share": (sell/total if total else None),
        "avg_trade_base": statistics.mean(sizes) if sizes else None,
        "median_trade_base": statistics.median(sizes) if sizes else None,
        "classification": classify_flow(buy_share),
    }

funding = safe_get(f"{OKX}/api/v5/public/funding-rate", {"instId": okx_swap})
out["sources"]["okx_funding_current"] = {k:v for k,v in funding.items() if k != "data"}
if funding["ok"] and funding["data"] and funding["data"].get("data"):
    fd = funding["data"]["data"][0]
    out["derivatives"]["funding_rate"] = float(fd["fundingRate"])
    out["derivatives"]["funding_time_ms"] = int(fd["fundingTime"]) if fd.get("fundingTime") else None
    out["derivatives"]["next_funding_time_ms"] = int(fd["nextFundingTime"]) if fd.get("nextFundingTime") else None

fh = safe_get(f"{OKX}/api/v5/public/funding-rate-history", {"instId": okx_swap, "limit": 8})
out["sources"]["okx_funding_history"] = {k:v for k,v in fh.items() if k != "data"}
if fh["ok"] and fh["data"] and fh["data"].get("data"):
    vals = [float(x["fundingRate"]) for x in fh["data"]["data"] if x.get("fundingRate") is not None]
    if vals:
        out["derivatives"]["funding_history_count"] = len(vals)
        out["derivatives"]["funding_avg_8"] = statistics.mean(vals)
        out["derivatives"]["funding_min_8"] = min(vals)
        out["derivatives"]["funding_max_8"] = max(vals)

oi = safe_get(f"{OKX}/api/v5/public/open-interest", {"instType": "SWAP", "instId": okx_swap})
out["sources"]["okx_open_interest_current"] = {k:v for k,v in oi.items() if k != "data"}
if oi["ok"] and oi["data"] and oi["data"].get("data"):
    od = oi["data"]["data"][0]
    out["derivatives"]["open_interest_contracts"] = float(od["oi"])
    if od.get("oiCcy"):
        out["derivatives"]["open_interest_base"] = float(od["oiCcy"])

pt = safe_get(f"{OKX}/api/v5/market/ticker", {"instId": okx_swap})
out["sources"]["okx_perp_ticker"] = {k:v for k,v in pt.items() if k != "data"}
if pt["ok"] and pt["data"] and pt["data"].get("data"):
    td = pt["data"]["data"][0]
    out["derivatives"]["perp_last_price"] = float(td["last"]) if td.get("last") else None

states = [v["ok"] for v in out["sources"].values()]
ok_count = sum(states)
failed_count = len(states) - ok_count
overall = "OK" if states and ok_count == len(states) else ("PARTIAL" if ok_count else "FAILED")
out["data_quality"] = {
    "status": overall,
    "sources_ok": ok_count,
    "sources_failed": failed_count,
    "liquidations_status": out["liquidations"]["status"],
}

print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))

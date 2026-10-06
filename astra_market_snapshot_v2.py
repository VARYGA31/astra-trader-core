#!/usr/bin/env python3
import sys, json, math, statistics
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

def ema(values, period):
    if len(values) < period:
        return None
    alpha = 2 / (period + 1)
    e = statistics.mean(values[:period])
    for v in values[period:]:
        e = alpha * v + (1 - alpha) * e
    return e

def rsi(values, period=14):
    if len(values) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        d = values[i] - values[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_gain = statistics.mean(gains[:period])
    avg_loss = statistics.mean(losses[:period])
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        trs.append(max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])))
    a = statistics.mean(trs[:period])
    for tr in trs[period:]:
        a = (a * (period - 1) + tr) / period
    return a

def realized_vol_pct(closes, periods=24):
    if len(closes) < periods + 1:
        return None
    rets = [math.log(closes[i]/closes[i-1]) for i in range(len(closes)-periods, len(closes)) if closes[i-1] > 0 and closes[i] > 0]
    return statistics.stdev(rets) * math.sqrt(periods) * 100 if len(rets) >= 2 else None

def classify_trend(c24, c4, price, e20, e50, e200):
    if None in (c24, c4, price, e20, e50):
        return "INSUFFICIENT_DATA"
    if e200 is not None and price > e20 > e50 > e200 and c24 > 0 and c4 > 0:
        return "STRONG_BULLISH"
    if e200 is not None and price < e20 < e50 < e200 and c24 < 0 and c4 < 0:
        return "STRONG_BEARISH"
    if price > e20 > e50 and c4 > 0:
        return "BULLISH"
    if price < e20 < e50 and c4 < 0:
        return "BEARISH"
    return "NEUTRAL"

def classify_momentum(r):
    if r is None: return "INSUFFICIENT_DATA"
    if r >= 70: return "OVERBOUGHT"
    if r <= 30: return "OVERSOLD"
    if r >= 55: return "BULLISH"
    if r <= 45: return "BEARISH"
    return "NEUTRAL"

def classify_vol(rv, atr_pct):
    vals = [x for x in (rv, atr_pct) if x is not None]
    if not vals: return "INSUFFICIENT_DATA"
    score = max(vals)
    if score >= 5: return "EXTREME"
    if score >= 2.5: return "HIGH"
    if score <= 0.8: return "LOW"
    return "NORMAL"

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

def classify_funding(f):
    if f is None: return "INSUFFICIENT_DATA"
    af = abs(f)
    if af >= 0.001: return "EXTREME"
    if af >= 0.0005: return "ELEVATED"
    if af <= 0.00005: return "LOW"
    return "NORMAL"

asset = (sys.argv[1] if len(sys.argv) > 1 else "BTC").upper()
spot_symbol = f"{asset}USDT"
okx_swap = f"{asset}-USDT-SWAP"

BINANCE = "https://data-api.binance.vision"
OKX = "https://www.okx.com"

out = {
    "asset": asset,
    "generated_at_utc": utc_now(),
    "spot": {}, "trend": {}, "technical": {}, "order_book": {}, "trade_flow": {},
    "derivatives": {},
    "liquidations": {"status": "UNAVAILABLE", "note": "No complete public liquidation feed is guaranteed by the selected APIs."},
    "market_state": {}, "sources": {}, "data_quality": {}
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

kl = safe_get(f"{BINANCE}/api/v3/klines", {"symbol": spot_symbol, "interval": "1h", "limit": 500})
out["sources"]["binance_klines_1h"] = {k:v for k,v in kl.items() if k != "data"}
if kl["ok"] and isinstance(kl["data"], list) and kl["data"]:
    rows = kl["data"]
    closes = [float(r[4]) for r in rows]
    highs = [float(r[2]) for r in rows]
    lows = [float(r[3]) for r in rows]
    vols = [float(r[5]) for r in rows]
    last = closes[-1]
    c1 = pct(closes[-2], last) if len(closes) >= 2 else None
    c4 = pct(closes[-5], last) if len(closes) >= 5 else None
    c24 = pct(closes[-25], last) if len(closes) >= 25 else None
    avg24 = statistics.mean(vols[-24:]) if len(vols) >= 24 else None
    e20, e50, e200 = ema(closes,20), ema(closes,50), ema(closes,200)
    r14 = rsi(closes,14)
    a14 = atr(highs,lows,closes,14)
    atr_pct = (a14/last*100) if a14 and last else None
    rv24 = realized_vol_pct(closes,24)
    out["trend"] = {
        "candles_1h_count": len(closes),
        "change_1h_pct": c1, "change_4h_pct": c4, "change_24h_pct": c24,
        "volume_last_1h_base": vols[-1] if vols else None,
        "volume_avg_24h_base": avg24,
        "volume_last_vs_avg_ratio": (vols[-1]/avg24 if vols and avg24 else None),
    }
    out["technical"] = {
        "ema20": e20, "ema50": e50, "ema200": e200,
        "price_vs_ema20_pct": pct(e20,last) if e20 else None,
        "price_vs_ema50_pct": pct(e50,last) if e50 else None,
        "price_vs_ema200_pct": pct(e200,last) if e200 else None,
        "rsi14": r14, "atr14": a14, "atr14_pct": atr_pct,
        "realized_volatility_24h_pct": rv24,
        "trend_regime": classify_trend(c24,c4,last,e20,e50,e200),
        "momentum_regime": classify_momentum(r14),
        "volatility_regime": classify_vol(rv24,atr_pct),
        "volume_regime": "ABOVE_AVERAGE" if avg24 and vols[-1] > avg24*1.2 else ("BELOW_AVERAGE" if avg24 and vols[-1] < avg24*0.8 else "NORMAL")
    }

depth = safe_get(f"{BINANCE}/api/v3/depth", {"symbol": spot_symbol, "limit": 20})
out["sources"]["binance_depth_top20"] = {k:v for k,v in depth.items() if k != "data"}
if depth["ok"] and isinstance(depth["data"], dict):
    bids = [(float(p),float(q)) for p,q in depth["data"].get("bids",[])]
    asks = [(float(p),float(q)) for p,q in depth["data"].get("asks",[])]
    if bids and asks:
        bid_vol = sum(q for _,q in bids); ask_vol = sum(q for _,q in asks)
        total = bid_vol + ask_vol
        imb = bid_vol/total if total else None
        best_bid, best_ask = bids[0][0], asks[0][0]
        mid = (best_bid+best_ask)/2
        out["order_book"] = {
            "best_bid": best_bid, "best_ask": best_ask,
            "spread_abs": best_ask-best_bid,
            "spread_pct": ((best_ask-best_bid)/mid*100 if mid else None),
            "bid_volume_top20": bid_vol, "ask_volume_top20": ask_vol,
            "imbalance": imb, "classification": classify_book(imb)
        }

tr = safe_get(f"{BINANCE}/api/v3/trades", {"symbol": spot_symbol, "limit": 500})
out["sources"]["binance_recent_trades"] = {k:v for k,v in tr.items() if k != "data"}
if tr["ok"] and isinstance(tr["data"], list):
    buy = sell = 0.0; sizes = []
    for x in tr["data"]:
        q = float(x["qty"]); sizes.append(q)
        if x.get("isBuyerMaker"): sell += q
        else: buy += q
    total = buy+sell
    buy_share = buy/total if total else None
    out["trade_flow"] = {
        "trades_count": len(tr["data"]),
        "aggressive_buy_base": buy, "aggressive_sell_base": sell,
        "buy_sell_ratio": (buy/sell if sell else None),
        "buy_share": buy_share, "sell_share": (sell/total if total else None),
        "avg_trade_base": statistics.mean(sizes) if sizes else None,
        "median_trade_base": statistics.median(sizes) if sizes else None,
        "classification": classify_flow(buy_share)
    }

funding = safe_get(f"{OKX}/api/v5/public/funding-rate", {"instId": okx_swap})
out["sources"]["okx_funding_current"] = {k:v for k,v in funding.items() if k != "data"}
if funding["ok"] and funding["data"] and funding["data"].get("data"):
    fd = funding["data"]["data"][0]
    fr = float(fd["fundingRate"])
    out["derivatives"]["funding_rate"] = fr
    out["derivatives"]["funding_regime"] = classify_funding(fr)
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

oi = safe_get(f"{OKX}/api/v5/public/open-interest", {"instType":"SWAP","instId":okx_swap})
out["sources"]["okx_open_interest_current"] = {k:v for k,v in oi.items() if k != "data"}
if oi["ok"] and oi["data"] and oi["data"].get("data"):
    od = oi["data"]["data"][0]
    out["derivatives"]["open_interest_contracts"] = float(od["oi"])
    if od.get("oiCcy"): out["derivatives"]["open_interest_base"] = float(od["oiCcy"])

pt = safe_get(f"{OKX}/api/v5/market/ticker", {"instId":okx_swap})
out["sources"]["okx_perp_ticker"] = {k:v for k,v in pt.items() if k != "data"}
if pt["ok"] and pt["data"] and pt["data"].get("data"):
    td = pt["data"]["data"][0]
    out["derivatives"]["perp_last_price"] = float(td["last"]) if td.get("last") else None

out["market_state"] = {
    "trend": out.get("technical",{}).get("trend_regime"),
    "momentum": out.get("technical",{}).get("momentum_regime"),
    "volatility": out.get("technical",{}).get("volatility_regime"),
    "volume": out.get("technical",{}).get("volume_regime"),
    "order_book": out.get("order_book",{}).get("classification"),
    "trade_flow": out.get("trade_flow",{}).get("classification"),
    "funding": out.get("derivatives",{}).get("funding_regime"),
}

states = [v["ok"] for v in out["sources"].values()]
ok_count = sum(1 for x in states if x)
failed_count = len(states)-ok_count
overall = "OK" if states and ok_count == len(states) else ("PARTIAL" if ok_count else "FAILED")
out["data_quality"] = {
    "status": overall, "sources_ok": ok_count, "sources_failed": failed_count,
    "liquidations_status": out["liquidations"]["status"]
}

print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))

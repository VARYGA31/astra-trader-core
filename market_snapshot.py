#!/usr/bin/env python3
import sys, json, math, statistics
from datetime import datetime, timezone
import requests
import config

from asset_map import ASSETS
import gold_macro

BINANCE = "https://data-api.binance.vision"
OKX = config.OKX_BASE_URL
TIMEOUT = 12
UA = {"User-Agent": "ASTRA-Trader-Market/2.0"}

def now():
    return datetime.now(timezone.utc).isoformat()

def _request_headers(url):
    headers=dict(UA)
    if str(config.EXECUTION_MODE).lower()=="okx_demo" and str(url).startswith(OKX):
        headers["x-simulated-trading"]="1"
    return headers

def get(url, params=None):
    r = requests.get(url, params=params, headers=_request_headers(url), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json(), r.status_code

def ema(values, period):
    if len(values) < period:
        return None
    k = 2/(period+1)
    e = sum(values[:period])/period
    for x in values[period:]:
        e = x*k + e*(1-k)
    return e

def rsi(values, period=14):
    if len(values) <= period:
        return None
    gains=[]; losses=[]
    for i in range(1, len(values)):
        d=values[i]-values[i-1]
        gains.append(max(d,0)); losses.append(max(-d,0))
    ag=sum(gains[:period])/period
    al=sum(losses[:period])/period
    for g,l in zip(gains[period:], losses[period:]):
        ag=(ag*(period-1)+g)/period
        al=(al*(period-1)+l)/period
    if al == 0:
        return 100.0
    return 100 - (100/(1+ag/al))

def atr(highs,lows,closes,period=14):
    if len(closes) <= period:
        return None
    trs=[]
    for i in range(1,len(closes)):
        trs.append(max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])))
    a=sum(trs[:period])/period
    for tr in trs[period:]:
        a=(a*(period-1)+tr)/period
    return a

def pct(a,b):
    if not b:
        return None
    return (a/b-1)*100

def regime(price,e20,e50,e200):
    if None in (e20,e50,e200):
        return "UNKNOWN"
    if price>e20>e50>e200:
        return "BULLISH"
    if price<e20<e50<e200:
        return "BEARISH"
    return "MIXED"

def _structure(highs, lows):
    if len(highs) < 12:
        return "UNKNOWN"
    # Compare the most recent 5 completed bars with the preceding 5.
    ph=max(highs[-10:-5]); pl=min(lows[-10:-5])
    rh=max(highs[-5:]); rl=min(lows[-5:])
    if rh > ph and rl > pl:
        return "BULLISH"
    if rh < ph and rl < pl:
        return "BEARISH"
    return "RANGE"

def _tf_features(rows, label):
    if len(rows) < 30:
        return {"status":"FAILED","timeframe":label,"reason":"INSUFFICIENT_CANDLES"}

    opens=[x["open"] for x in rows]
    highs=[x["high"] for x in rows]
    lows=[x["low"] for x in rows]
    closes=[x["close"] for x in rows]
    vols=[x["volume"] for x in rows]

    price=closes[-1]
    e20=ema(closes,20); e50=ema(closes,50); e200=ema(closes,200)
    rr=rsi(closes,14)
    aa=atr(highs,lows,closes,14)
    structure=_structure(highs,lows)

    prior_high=max(highs[-21:-1]) if len(highs)>=21 else max(highs[:-1])
    prior_low=min(lows[-21:-1]) if len(lows)>=21 else min(lows[:-1])
    breakout_up=price > prior_high
    breakout_down=price < prior_low

    avg20=(sum(vols[-21:-1])/20) if len(vols)>=21 else (sum(vols[:-1])/max(1,len(vols)-1))
    vol_ratio=(vols[-1]/avg20) if avg20 else None
    a_pct=(aa/price*100) if aa and price else None
    body_pct=(abs(closes[-1]-opens[-1])/price*100) if price else None

    return {
        "status":"OK",
        "timeframe":label,
        "last_confirmed_close_time_ms":rows[-1]["close_time_ms"],
        "close":price,
        "changes_pct":{
            "1bar":pct(closes[-1],closes[-2]) if len(closes)>=2 else None,
            "3bar":pct(closes[-1],closes[-4]) if len(closes)>=4 else None,
            "6bar":pct(closes[-1],closes[-7]) if len(closes)>=7 else None,
        },
        "indicators":{
            "ema20":e20,
            "ema50":e50,
            "ema200":e200,
            "rsi14":rr,
            "atr14":aa,
            "atr_pct":a_pct,
        },
        "regimes":{
            "trend":regime(price,e20,e50,e200),
            "momentum":"BULLISH" if (rr or 50)>55 else "BEARISH" if (rr or 50)<45 else "NEUTRAL",
            "structure":structure,
        },
        "structure":{
            "prior_20_high":prior_high,
            "prior_20_low":prior_low,
            "breakout_up":breakout_up,
            "breakout_down":breakout_down,
            "distance_to_prior_high_pct":((prior_high/price)-1)*100 if price else None,
            "distance_to_prior_low_pct":(1-(prior_low/price))*100 if price else None,
        },
        "volume":{
            "last":vols[-1],
            "avg20":avg20,
            "ratio_to_avg20":vol_ratio,
        },
        "last_candle":{
            "open":opens[-1],
            "high":highs[-1],
            "low":lows[-1],
            "close":closes[-1],
            "body_pct":body_pct,
            "body_atr":(abs(closes[-1]-opens[-1])/aa) if aa else None,
        },
    }

def _okx_confirmed_candles(inst, bar, limit=300):
    x,_=get(OKX+"/api/v5/market/candles",{"instId":inst,"bar":bar,"limit":str(limit)})
    raw=x.get("data",[])
    rows=[]
    # OKX returns newest first. Use confirmed bars only where possible.
    for a in reversed(raw):
        try:
            confirm = str(a[8]) if len(a) > 8 else "1"
            if confirm != "1":
                continue
            rows.append({
                "open_time_ms":int(a[0]),
                "open":float(a[1]),
                "high":float(a[2]),
                "low":float(a[3]),
                "close":float(a[4]),
                "volume":float(a[5]),
                # OKX candle timestamp is the bar start; approximate close time from next row
                # isn't needed for dedupe, so use timestamp as stable bar id.
                "close_time_ms":int(a[0]),
            })
        except Exception:
            continue
    return rows

def okx_multi_timeframe(inst, include_micro=False):
    frames={}
    errors=[]
    pairs=[("5m","5m"),("15m","15m"),("1h","1H"),("4h","4H")]
    if include_micro:
        pairs=[("1m","1m"),("3m","3m")]+pairs
    for name,bar in pairs:
        try:
            rows=_okx_confirmed_candles(inst,bar,300)
            frames[name]=_tf_features(rows,name)
        except Exception as e:
            frames[name]={"status":"FAILED","timeframe":name,"error":str(e)}
            errors.append(f"{name}:{e}")
    ok=sum(1 for x in frames.values() if x.get("status")=="OK")
    expected=len(pairs)
    return {
        "status":"OK" if ok==expected else "PARTIAL" if ok else "FAILED",
        "source":"OKX_SWAP_CONFIRMED_CANDLES",
        "frames":frames,
        "errors":errors,
    }

def spot_binance(symbol):
    tick,_=get(BINANCE+"/api/v3/ticker/24hr",{"symbol":symbol})
    kl,_=get(BINANCE+"/api/v3/klines",{"symbol":symbol,"interval":"1h","limit":500})
    depth,_=get(BINANCE+"/api/v3/depth",{"symbol":symbol,"limit":20})
    trades,_=get(BINANCE+"/api/v3/trades",{"symbol":symbol,"limit":500})
    closes=[float(x[4]) for x in kl]; highs=[float(x[2]) for x in kl]; lows=[float(x[3]) for x in kl]
    price=float(tick["lastPrice"])
    e20,e50,e200=ema(closes,20),ema(closes,50),ema(closes,200)
    rv=None
    if len(closes)>=25:
        rets=[math.log(closes[i]/closes[i-1]) for i in range(len(closes)-24,len(closes))]
        rv=statistics.pstdev(rets)*math.sqrt(24)*100
    a=atr(highs,lows,closes,14)
    bids=sum(float(p)*float(q) for p,q in depth.get("bids",[]))
    asks=sum(float(p)*float(q) for p,q in depth.get("asks",[]))
    imbalance=(bids-asks)/(bids+asks) if bids+asks else None
    buy=0.0; sell=0.0
    for t in trades:
        notional=float(t["price"])*float(t["qty"])
        if t.get("isBuyerMaker"): sell+=notional
        else: buy+=notional
    return {
        "price":price,
        "ticker_24h":{"high":float(tick["highPrice"]),"low":float(tick["lowPrice"]),"volume_base":float(tick["volume"]),"volume_quote":float(tick["quoteVolume"])},
        "changes_pct":{"1h":pct(closes[-1],closes[-2]),"4h":pct(closes[-1],closes[-5]),"24h":pct(closes[-1],closes[-25])},
        "indicators":{"ema20":e20,"ema50":e50,"ema200":e200,"rsi14":rsi(closes,14),"atr14":a,"atr_pct":(a/price*100 if a else None),"realized_vol_24h_pct":rv},
        "regimes":{"trend":regime(price,e20,e50,e200),"momentum":"BULLISH" if (rsi(closes,14) or 50)>55 else "BEARISH" if (rsi(closes,14) or 50)<45 else "NEUTRAL"},
        "order_book":{"bid_notional_top20":bids,"ask_notional_top20":asks,"imbalance":imbalance},
        "trade_flow":{"aggressive_buy_usd":buy,"aggressive_sell_usd":sell,"buy_sell_ratio":buy/sell if sell else None},
        "last_candle_close_time_ms":int(kl[-1][6]) if kl else None,
    }

def okx_reference_market(inst):
    """Spot-like technical context built from the OKX swap itself.

    Used for XAU because XAU-USDT-SWAP is the tradable commodity perpetual
    while a matching crypto-style spot market is not assumed.
    """
    tick,_=get(OKX+"/api/v5/market/ticker",{"instId":inst})
    td=tick.get("data",[])
    if not td:
        raise RuntimeError("OKX_REFERENCE_TICKER_EMPTY")
    td=td[0]

    rows=_okx_confirmed_candles(inst,"1H",300)
    if len(rows)<30:
        raise RuntimeError("OKX_REFERENCE_CANDLES_INSUFFICIENT")

    opens=[x["open"] for x in rows]
    highs=[x["high"] for x in rows]
    lows=[x["low"] for x in rows]
    closes=[x["close"] for x in rows]
    vols=[x["volume"] for x in rows]
    price=float(td.get("last") or closes[-1])

    e20,e50,e200=ema(closes,20),ema(closes,50),ema(closes,200)
    rr=rsi(closes,14)
    aa=atr(highs,lows,closes,14)

    depth,_=get(OKX+"/api/v5/market/books",{"instId":inst,"sz":"20"})
    book=(depth.get("data") or [{}])[0]
    bids=sum(float(x[0])*float(x[1]) for x in book.get("bids",[]))
    asks=sum(float(x[0])*float(x[1]) for x in book.get("asks",[]))
    imbalance=(bids-asks)/(bids+asks) if bids+asks else None

    trades,_=get(OKX+"/api/v5/market/trades",{"instId":inst,"limit":"500"})
    buy=sell=0.0
    for t in trades.get("data",[]):
        try:
            notional=float(t["px"])*float(t["sz"])
            if str(t.get("side","")).lower()=="buy":
                buy+=notional
            else:
                sell+=notional
        except Exception:
            continue

    return {
        "price":price,
        "ticker_24h":{
            "high":float(td["high24h"]) if td.get("high24h") else None,
            "low":float(td["low24h"]) if td.get("low24h") else None,
            "volume_base":float(td["vol24h"]) if td.get("vol24h") else None,
            "volume_quote":float(td["volCcy24h"]) if td.get("volCcy24h") else None,
        },
        "changes_pct":{
            "1h":pct(closes[-1],closes[-2]) if len(closes)>=2 else None,
            "4h":pct(closes[-1],closes[-5]) if len(closes)>=5 else None,
            "24h":pct(closes[-1],closes[-25]) if len(closes)>=25 else None,
        },
        "indicators":{
            "ema20":e20,"ema50":e50,"ema200":e200,
            "rsi14":rr,"atr14":aa,
            "atr_pct":(aa/price*100 if aa else None),
            "realized_vol_24h_pct":None,
        },
        "regimes":{
            "trend":regime(price,e20,e50,e200),
            "momentum":"BULLISH" if (rr or 50)>55 else "BEARISH" if (rr or 50)<45 else "NEUTRAL",
            "structure":_structure(highs,lows),
        },
        "order_book":{
            "bid_notional_top20":bids,
            "ask_notional_top20":asks,
            "imbalance":imbalance,
        },
        "trade_flow":{
            "aggressive_buy_usd":buy,
            "aggressive_sell_usd":sell,
            "buy_sell_ratio":buy/sell if sell else None,
        },
        "last_candle_close_time_ms":rows[-1]["close_time_ms"],
    }

def okx_microstructure_rest(inst):
    """Same-venue MICRO fallback when the WebSocket cache is not ready."""
    depth,_=get(OKX+"/api/v5/market/books",{"instId":inst,"sz":"20"})
    book=(depth.get("data") or [{}])[0]
    bids=book.get("bids") or []
    asks=book.get("asks") or []
    def notion(xs):
        total=0.0
        for x in xs[:20]:
            try: total+=float(x[0])*float(x[1])
            except Exception: pass
        return total
    b=notion(bids); a=notion(asks)
    bid=float(bids[0][0]) if bids else None
    ask=float(asks[0][0]) if asks else None
    imbalance=(b-a)/(b+a) if b+a else None

    trades,_=get(OKX+"/api/v5/market/trades",{"instId":inst,"limit":"500"})
    buy=sell=0.0
    for t in trades.get("data",[]):
        try:
            w=float(t.get("px") or 0)*float(t.get("sz") or 0)
            if str(t.get("side") or "").lower()=="buy": buy+=w
            else: sell+=w
        except Exception:
            continue
    mid=((bid+ask)/2.0) if bid and ask else None
    return {
        "status":"OK",
        "source":"OKX_REST_BOOKS20_TRADES",
        "order_book":{
            "bid_notional_top20":b,
            "ask_notional_top20":a,
            "imbalance":imbalance,
            "bid":bid,
            "ask":ask,
        },
        "trade_flow":{
            "aggressive_buy_weight":buy,
            "aggressive_sell_weight":sell,
            "buy_sell_ratio":(buy/sell) if sell else (None if buy<=0 else 99.0),
        },
        "bid":bid,"ask":ask,
        "spread_pct":((ask-bid)/mid*100.0) if mid and ask>=bid else None,
    }

def okx_swap(inst):
    out={}
    # Tradable perpetual reference used by ASTRA and the execution layer.
    try:
        x,_=get(OKX+"/api/v5/market/ticker",{"instId":inst})
        d=x.get("data",[])
        if d:
            t=d[0]
            out["last_price"]=float(t["last"]) if t.get("last") else None
            out["bid_price"]=float(t["bidPx"]) if t.get("bidPx") else None
            out["ask_price"]=float(t["askPx"]) if t.get("askPx") else None
            out["timestamp_ms"]=int(t["ts"]) if t.get("ts") else None
    except Exception as e:
        out["ticker_error"]=str(e)
    try:
        x,_=get(OKX+"/api/v5/public/funding-rate",{"instId":inst})
        d=x.get("data",[])
        if d: out["funding_rate"]=float(d[0]["fundingRate"])
    except Exception as e: out["funding_error"]=str(e)
    try:
        x,_=get(OKX+"/api/v5/public/open-interest",{"instType":"SWAP","instId":inst})
        d=x.get("data",[])
        if d: out["open_interest_contracts"]=float(d[0]["oi"])
    except Exception as e: out["oi_error"]=str(e)
    return out

def okx_spot_price(inst):
    x,_=get(OKX+"/api/v5/market/ticker",{"instId":inst})
    d=x.get("data",[])
    if not d: raise RuntimeError("OKX spot ticker empty")
    return float(d[0]["last"])

def snapshot(asset, include_micro=False):
    if asset not in ASSETS:
        return {"status":"TRADE_NOT_ALLOWED","requested_asset":asset,"allowed_assets":list(ASSETS)}

    cfg=ASSETS[asset]
    errors=[]
    spot=None

    if str(config.EXECUTION_MODE).lower()=="okx_demo":
        # OKX explicitly separates demo market data from production market data.
        # In demo mode every price-sensitive feature must therefore use the same
        # simulated swap environment as order execution; mixing Binance/live OKX
        # with demo execution creates artificial drift and invalid R:R levels.
        source="okx_demo_swap_reference"
        try:
            spot=okx_reference_market(cfg["okx_swap"])
        except Exception as e:
            errors.append("okx_demo_reference:"+str(e))
    elif asset=="XAU":
        source="okx_xau_swap_reference"
        try:
            spot=okx_reference_market(cfg["okx_swap"])
        except Exception as e:
            errors.append("okx_xau_reference:"+str(e))
    elif not cfg.get("binance_spot"):
        # Assets without a Binance spot market use the tradable OKX swap itself
        # as the technical/order-flow reference.
        source="okx_swap_reference"
        try:
            spot=okx_reference_market(cfg["okx_swap"])
        except Exception as e:
            errors.append("okx_reference:"+str(e))
    else:
        source="binance"
        try:
            spot=spot_binance(cfg["binance_spot"])
        except Exception as e:
            errors.append("binance:"+str(e))
            source="okx_fallback"
            try:
                if cfg.get("okx_spot"):
                    spot={"price":okx_spot_price(cfg["okx_spot"])}
            except Exception as e2:
                errors.append("okx_spot:"+str(e2))

    # MICRO decisions use OKX-native order book/trade flow, because execution
    # also happens on the OKX swap. Binance remains only the broad spot context.
    if include_micro and asset in set(config.MICRO_ALLOWED_ASSETS) and spot:
        micro=None
        try:
            import micro_market_stream
            micro_market_stream.ensure_started()
            micro=micro_market_stream.snapshot(asset)
        except Exception as e:
            errors.append("micro_ws:"+str(e))
        if not micro or micro.get("status")!="OK":
            try:
                micro=okx_microstructure_rest(cfg["okx_swap"])
            except Exception as e:
                errors.append("micro_rest:"+str(e))
                micro=None
        if micro and micro.get("status")=="OK":
            spot=dict(spot)
            spot["order_book"]=micro.get("order_book") or {}
            spot["trade_flow"]=micro.get("trade_flow") or {}
            spot["microstructure_source"]=micro.get("source")
            spot["microstructure_age_seconds"]=micro.get("age_seconds")
            spot["microstructure_spread_pct"]=micro.get("spread_pct")

    perp=okx_swap(cfg["okx_swap"])
    mtf=okx_multi_timeframe(cfg["okx_swap"],include_micro=include_micro)
    gmacro=gold_macro.snapshot() if asset=="XAU" else None

    quality="OK" if spot and spot.get("price") and mtf.get("status")!="FAILED" else "FAILED"
    if quality=="OK" and (errors or mtf.get("status")=="PARTIAL"):
        quality="PARTIAL"

    if asset=="XAU" and gmacro and gmacro.get("status")=="PARTIAL" and quality=="OK":
        quality="PARTIAL"

    return {
        "status":"OK" if quality!="FAILED" else "FAILED",
        "asset":asset,
        "generated_at_utc":now(),
        "spot_source":source,
        "spot":spot or {},
        "multi_timeframe":mtf,
        "perp_okx":perp,
        "gold_macro":gmacro,
        "liquidations":{"status":"UNAVAILABLE","note":"No complete free liquidation feed configured; never infer missing data."},
        "data_quality":{"status":quality,"errors":errors + mtf.get("errors",[])},
    }

if __name__=="__main__":
    asset=(sys.argv[1] if len(sys.argv)>1 else "BTC").upper()
    print(json.dumps(snapshot(asset),ensure_ascii=False,separators=(",",":")))

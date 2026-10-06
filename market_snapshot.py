#!/usr/bin/env python3
import sys, json, math, statistics
from datetime import datetime, timezone
import requests

from asset_map import ASSETS

BINANCE = "https://data-api.binance.vision"
OKX = "https://www.okx.com"
TIMEOUT = 12
UA = {"User-Agent": "ASTRA-Trader-Market/1.0"}

def now():
    return datetime.now(timezone.utc).isoformat()

def get(url, params=None):
    r = requests.get(url, params=params, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json(), r.status_code

def ema(values, period):
    if len(values) < period: return None
    k = 2/(period+1)
    e = sum(values[:period])/period
    for x in values[period:]:
        e = x*k + e*(1-k)
    return e

def rsi(values, period=14):
    if len(values) <= period: return None
    gains=[]; losses=[]
    for i in range(1, len(values)):
        d=values[i]-values[i-1]
        gains.append(max(d,0)); losses.append(max(-d,0))
    ag=sum(gains[:period])/period; al=sum(losses[:period])/period
    for g,l in zip(gains[period:], losses[period:]):
        ag=(ag*(period-1)+g)/period; al=(al*(period-1)+l)/period
    if al == 0: return 100.0
    return 100 - (100/(1+ag/al))

def atr(highs,lows,closes,period=14):
    if len(closes) <= period: return None
    trs=[]
    for i in range(1,len(closes)):
        trs.append(max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])))
    a=sum(trs[:period])/period
    for tr in trs[period:]:
        a=(a*(period-1)+tr)/period
    return a

def pct(a,b):
    if not b: return None
    return (a/b-1)*100

def regime(price,e20,e50,e200):
    if None in (e20,e50,e200): return "UNKNOWN"
    if price>e20>e50>e200: return "BULLISH"
    if price<e20<e50<e200: return "BEARISH"
    return "MIXED"

def spot_binance(symbol):
    tick,_=get(BINANCE+"/api/v3/ticker/24hr",{"symbol":symbol})
    kl,_=get(BINANCE+"/api/v3/klines",{"symbol":symbol,"interval":"1h","limit":500})
    depth,_=get(BINANCE+"/api/v3/depth",{"symbol":symbol,"limit":20})
    trades,_=get(BINANCE+"/api/v3/trades",{"symbol":symbol,"limit":500})
    closes=[float(x[4]) for x in kl]; highs=[float(x[2]) for x in kl]; lows=[float(x[3]) for x in kl]; vols=[float(x[5]) for x in kl]
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

def okx_swap(inst):
    out={}
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

def snapshot(asset):
    if asset not in ASSETS:
        return {"status":"TRADE_NOT_ALLOWED","requested_asset":asset,"allowed_assets":list(ASSETS)}
    cfg=ASSETS[asset]; errors=[]; spot=None; source="binance"
    try:
        spot=spot_binance(cfg["binance_spot"])
    except Exception as e:
        errors.append("binance:"+str(e))
        source="okx_fallback"
        try:
            spot={"price":okx_spot_price(cfg["okx_spot"])}
        except Exception as e2:
            errors.append("okx_spot:"+str(e2))
    perp=okx_swap(cfg["okx_swap"])
    quality="OK" if spot and spot.get("price") else "FAILED"
    if quality=="OK" and errors: quality="PARTIAL"
    return {
        "status":"OK" if quality!="FAILED" else "FAILED",
        "asset":asset,
        "generated_at_utc":now(),
        "spot_source":source,
        "spot":spot or {},
        "perp_okx":perp,
        "liquidations":{"status":"UNAVAILABLE","note":"No complete free liquidation feed configured; never infer missing data."},
        "data_quality":{"status":quality,"errors":errors},
    }

if __name__=="__main__":
    asset=(sys.argv[1] if len(sys.argv)>1 else "BTC").upper()
    print(json.dumps(snapshot(asset),ensure_ascii=False,separators=(",",":")))

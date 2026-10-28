#!/usr/bin/env python3
"""Standalone no-order research of two predeclared ASTRA market-regime entries.

Uses public OKX confirmed swap candles and existing causal MTF indicators.
NO LLM, no private credentials, no live trade/risk/router modifications.
Stop-first within an OHLC candle; next 15m open; realistic execution still
requires FOK/spread/slippage/funding modelling and paper validation.
"""
import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import historical_normal_research as h
import market_snapshot
from asset_map import ASSETS

STRATEGIES=("normal","compression_breakout","range_reversion")


def signal(frames,bars,index):
    """Evaluate a signal ONLY after bar[index] is confirmed closed."""
    tf4,tf1,tf15=(frames[k] for k in ("4h","1h","15m"))
    if index<35:
        return {}
    bar=bars[index]
    price=bar["close"]
    atr1=tf1["indicators"].get("atr_pct")
    atr15=tf15["indicators"].get("atr_pct")
    vol=tf15["volume"].get("ratio_to_avg20")
    if not all(isinstance(x,(int,float)) and math.isfinite(x) and x>0
               for x in (price,atr1,atr15,vol)):
        return {}
    r4=tf4["regimes"]
    r1=tf1["regimes"]
    r15=tf15["regimes"]
    out={}

    # H1: tight 3h compression, 15m breakout on >=1.2x volume,
    # while 1h structure and 4h momentum do not fight the direction.
    prior=bars[index-12:index]  # excludes signal bar; no future data
    span_pct=100*(max(x["high"] for x in prior)-
                 min(x["low"] for x in prior))/price
    if span_pct<=1.25*atr1 and vol>=1.2:
        above=price>max(x["high"] for x in prior)
        below=price<min(x["low"] for x in prior)
        if (above and r1["structure"]=="BULLISH"
            and r4["momentum"]!="BEARISH"):
            out["compression_breakout"]=("LONG",max(0.5,min(3.0,1.25*atr15)),2.0)
        if (below and r1["structure"]=="BEARISH"
            and r4["momentum"]!="BULLISH"):
            out["compression_breakout"]=("SHORT",max(0.5,min(3.0,1.25*atr15)),2.0)

    # H2: true mixed macro + 1h sideways, 15m RSI extreme with
    # distance of at least 0.8x 15m ATR from EMA20. Fixed 1.5R TP.
    rsi=tf15["indicators"].get("rsi14")
    ema=tf15["indicators"].get("ema20")
    if (r4.get("trend")=="MIXED"
        and r1.get("trend")=="MIXED"
        and r1.get("structure")=="RANGE"
        and isinstance(rsi,(int,float))
        and isinstance(ema,(int,float)) and ema>0 and vol>=0.5):
        dist=100*(price/ema-1)
        stop=max(0.5,min(2.0,1.25*atr15))
        if rsi<=30 and dist<=-0.8*atr15:
            out["range_reversion"]=("LONG",stop,1.5)
        elif rsi>=70 and dist>=0.8*atr15:
            out["range_reversion"]=("SHORT",stop,1.5)
    return out


def trade(bars,index,direction,stop_pct,tp_r,cost_pct=0.14,horizon=16):
    """Conservative next-open fill, with stop precedence in ambiguous bars."""
    if index+1>=len(bars):
        return None
    entry=float(bars[index+1]["open"])
    if not math.isfinite(entry) or entry<=0:
        return None
    sign=1 if direction=="LONG" else -1
    stop=entry*(1-sign*stop_pct/100)
    tp=entry*(1+sign*stop_pct*tp_r/100)
    end=min(index+horizon,len(bars)-1)
    px=bars[end]["close"]; reason="TIME"
    for j in range(index+1,end+1):
        x=bars[j]
        if x["low"]<=stop if sign==1 else x["high"]>=stop:
            px=stop;end=j;reason="STOP";break
        if x["high"]>=tp if sign==1 else x["low"]<=tp:
            px=tp;end=j;reason="TP";break
    gross_pct=(px/entry-1)*sign*100
    return {"end_index":end,"exit_reason":reason,"stop_pct":stop_pct,
            "gross_pct":gross_pct,"net_r":(gross_pct-cost_pct)/stop_pct}


def analyze(rows_by_tf,asset,from_ms,to_ms,cost_pct=0.14):
    starts={k:[x["open_time_ms"] for x in rows] for k,rows in rows_by_tf.items()}
    bars=rows_by_tf["15m"]
    split=from_ms+int((to_ms-from_ms)*0.7)
    last_end={k:-1 for k in STRATEGIES}
    result={k:[] for k in STRATEGIES}
    diag={"missing_asof_frames":0,"candles_evaluated":0}
    # Cache repeated 1h/4h indicators without changing source data or rule.
    frames_cache={}
    for idx in range(len(bars)-1):
        asof=bars[idx]["open_time_ms"]+h.BAR["15m"]
        if not from_ms<=asof<to_ms:
            continue
        frame={}
        for tf in ("4h","1h","15m"):
            if tf=="15m":
                f=h.frame_at(rows_by_tf[tf],starts[tf],asof,tf)
            else:
                # h.frame_at performs closed-bar selection. Key contains only
                # the completed timeframe boundary (not the signal's future).
                key=(tf,asof//h.BAR[tf])
                if key not in frames_cache:
                    frames_cache[key]=h.frame_at(rows_by_tf[tf],starts[tf],asof,tf)
                f=frames_cache[key]
            frame[tf]=f
        if any(x is None or x.get("status")!="OK" for x in frame.values()):
            diag["missing_asof_frames"]+=1
            continue
        diag["candles_evaluated"]+=1
        choices=signal(frame,bars,idx)
        baseline=h.signals(frame,asset)["normal"]
        if baseline:
            atr=float(frame["1h"]["indicators"].get("atr_pct") or 0)
            choices["normal"]=(baseline[0],max(0.5,min(3.0,1.25*atr)),2.0)
        for mode,setup in choices.items():
            if idx<=last_end[mode]:
                continue
            direction,stop,tp=setup
            outcome=trade(bars,idx,direction,stop,tp,cost_pct,
                          horizon=12 if mode=="range_reversion" else 16)
            if outcome is None:
                continue
            last_end[mode]=outcome["end_index"]
            result[mode].append({"asset":asset,"signal_time_ms":asof,
                "phase":"validation" if asof>=split else "development",
                "strategy":mode,**outcome})
    return result,diag


def metrics(rows,stress_cost=0.24,base_cost=0.14):
    vals=[r["net_r"] for r in rows]
    scores=h.metrics(rows)
    if not vals:
        scores["stress_avg_net_r"]=None
        scores["stress_profit_factor"]=None
        return scores
    stressed=[{**r,"net_r":r["net_r"]-(stress_cost-base_cost)/r["stop_pct"]}
              for r in rows]
    st=h.metrics(stressed)
    scores["stress_avg_net_r"]=st["avg_net_r"]
    scores["stress_profit_factor"]=st["profit_factor"]
    return scores


def run(days,assets,cost_pct=0.14,max_pages=600):
    now=datetime.now(timezone.utc).replace(second=0,microsecond=0)
    to_ms=int(now.timestamp()*1000)
    from_ms=int((now-timedelta(days=days)).timestamp()*1000)
    warm_ms=int((now-timedelta(days=days+39)).timestamp()*1000)
    combined={k:[] for k in STRATEGIES}
    per_asset={}
    errors={}
    with requests.Session() as session:
        for asset in assets:
            if asset not in ASSETS or asset=="GRAM":
                errors[asset]="UNKNOWN_OR_DISABLED_ASSET";continue
            try:
                data={}
                for tf in ("4h","1h","15m"):
                    data[tf]=h.fetch(session,ASSETS[asset]["okx_swap"],tf,
                                     warm_ms,to_ms,max_pages=max_pages)
                trades,diag=analyze(data,asset,from_ms,to_ms,cost_pct)
                per_asset[asset]={"diagnostics":diag,"strategies":{
                    mode:{phase:metrics([r for r in trades[mode] if r["phase"]==phase],
                                        base_cost=cost_pct)
                          for phase in ("development","validation")}
                    for mode in STRATEGIES}}
                for k in STRATEGIES:
                    combined[k].extend(trades[k])
            except (RuntimeError,requests.RequestException,ValueError) as e:
                errors[asset]=type(e).__name__+":"+str(e)[:150]
                continue
    merged={}
    for mode in STRATEGIES:
        merged[mode]={phase:metrics(
            sorted([r for r in combined[mode] if r["phase"]==phase],
                   key=lambda r:r["signal_time_ms"]),base_cost=cost_pct)
            for phase in ("development","validation")}
    return {"status":"RESEARCH_ONLY" if per_asset and not errors else
                "PARTIAL" if per_asset else "DATA_UNAVAILABLE",
        "orders_possible":False,"asof_utc":now.isoformat(),
        "data_source":"OKX_PUBLIC_CONFIRMED_SWAP_CANDLES_NOT_DEMO",
        "days":days,"assets":per_asset,"data_errors":errors,"overall":merged,
        "assumed_roundtrip_friction_pct":cost_pct,
        "stress_roundtrip_friction_pct":0.24,
        "split":"chronological_70pct_development_30pct_validation",
        "predeclared_rules":{
            "compression_breakout":"3h range <=1.25x 1h ATR; 15m break with volume >=1.2; 1h structure; 4h momentum not opposite; 2R TP",
            "range_reversion":"4h/1h MIXED, 1h RANGE structure, 15m RSI <=30 or >=70, distance >=0.8x ATR, volume >=0.5; 1.5R TP",
        },
        "limitations":"NOT live/demo backtest: no LLM, news, FOK, exact funding/spreads, correlation, position sizing or execution slippage; overlapping assets/correlated trades may inflate evidence"}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--days",type=int,default=90)
    ap.add_argument("--assets",nargs="+",default=["BTC","ETH","AAVE"])
    ap.add_argument("--output",default="regime_lab_report.json")
    ap.add_argument("--cost-pct",type=float,default=0.14)
    ap.add_argument("--max-pages",type=int,default=600)
    a=ap.parse_args()
    if not 14<=a.days<=365 or not 0<=a.cost_pct<=1:
        ap.error("invalid days or friction")
    report=run(a.days,a.assets,a.cost_pct,a.max_pages)
    Path(a.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),
                              encoding="utf-8")
    print("ASTRA_REGIME_LAB_RESULT="+json.dumps(report,ensure_ascii=False),flush=True)
    if report["status"]=="DATA_UNAVAILABLE":
        raise SystemExit(2)


if __name__=="__main__":
    main()

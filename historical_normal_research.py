#!/usr/bin/env python3
"""Historical ASTRA MTF research. No orders, API keys, worker, or LLM.

Public OKX swap candles are NOT demo bid/ask data. Results exclude funding,
FOK, news, exposure, and actual LLM stops and MUST NOT promote a live rule.
"""
import argparse
import bisect
import json
import math
import statistics
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import config
import market_snapshot
import mtf_gate
from asset_map import ASSETS

BAR={"15m":900000,"1h":3600000,"4h":14400000}
API_BAR={"15m":"15m","1h":"1H","4h":"4H"}
API="https://www.okx.com/api/v5/market/history-candles"
MODES=("normal","mixed_72","mixed_66")


def fetch(session, inst, tf, since_ms, end_ms, max_pages=600):
    cursor=end_ms+1
    got={}
    for _ in range(max_pages):
        for attempt in range(3):
            try:
                res=session.get(API,params={"instId":inst,"bar":API_BAR[tf],
                    "after":str(cursor),"limit":"100"},timeout=18)
                res.raise_for_status()
                body=res.json()
                if str(body.get("code"))!="0" or not isinstance(body.get("data"),list):
                    raise ValueError("BAD_OKX_RESPONSE")
                raw=body["data"]
                break
            except (requests.RequestException,ValueError) as exc:
                if attempt==2:
                    raise RuntimeError("DATA_UNAVAILABLE "+inst+" "+tf+" "+str(exc)[:80])
                time.sleep(0.6*(attempt+1))
        if not raw:
            break
        oldest=min(int(x[0]) for x in raw)
        if oldest>=cursor:
            raise RuntimeError("PAGINATION_STUCK "+inst+" "+tf)
        for x in raw:
            if len(x)<9 or str(x[8])!="1":
                continue
            try:
                ts=int(x[0])
                if not since_ms<=ts<end_ms:
                    continue
                row={"open_time_ms":ts,"close_time_ms":ts,"open":float(x[1]),
                    "high":float(x[2]),"low":float(x[3]),"close":float(x[4]),
                    "volume":float(x[5])}
                if all(math.isfinite(row[k]) for k in ("open","high","low","close","volume")) and row["close"]>0:
                    got[ts]=row
            except (ValueError,TypeError,IndexError):
                continue
        cursor=oldest
        if cursor<since_ms:
            break
        time.sleep(0.24)
    rows=[got[k] for k in sorted(got)]
    if not rows or rows[0]["open_time_ms"]>since_ms+2*BAR[tf]:
        raise RuntimeError("INSUFFICIENT_HISTORY "+inst+" "+tf)
    if rows[-1]["open_time_ms"]<end_ms-3*BAR[tf]:
        raise RuntimeError("STALE_HISTORY "+inst+" "+tf)
    gaps=sum((b["open_time_ms"]-a["open_time_ms"])>2*BAR[tf]
        and not (inst.startswith("XAU-") and
                 b["open_time_ms"]-a["open_time_ms"]<=72*3600000)
        for a,b in zip(rows,rows[1:]))
    if gaps>max(3,len(rows)//100):
        raise RuntimeError("HISTORY_GAPS "+inst+" "+tf+" "+str(gaps))
    return rows


def frame_at(rows, ts, asof, tf):
    # Candle is visible only after its closing time.
    idx=bisect.bisect_right(ts,asof-BAR[tf])-1
    if idx<199:
        return None
    if asof-(ts[idx]+BAR[tf])>2*BAR[tf]:
        return None
    return market_snapshot._tf_features(rows[max(0,idx-299):idx+1],tf)


def signals(frames, asset):
    p={"asset":asset,"decision_context":{"market":{"multi_timeframe":{
        "status":"OK","frames":frames}}}}
    result=mtf_gate.evaluate(p)
    out={name:None for name in MODES}
    if result.get("passed") and result.get("mode")=="NORMAL":
        out={name:(result["direction"],result["quality"]) for name in MODES}
        return out
    f4=frames["4h"]
    if f4.get("regimes",{}).get("trend")!="MIXED":
        return out
    for c in result["candidates"]:
        direction=c["direction"]
        trig=c["trigger_15m"]
        vol=frames["15m"]["volume"].get("ratio_to_avg20")
        if not (c["regime_4h_ok"] is False
                and mtf_gate._transition_4h_ok(f4,direction)
                and c["setup_1h_ok"] and trig["confirmed"] and trig["count"]>=4
                and isinstance(vol,(float,int)) and vol>=0.90):
            continue
        for mode,floor in (("mixed_72",72),("mixed_66",66)):
            if asset=="XAU":
                floor=max(floor,config.XAU_MTF_MIN_QUALITY)
            if c["quality"]>=floor and (out[mode] is None or c["quality"]>out[mode][1]):
                out[mode]=(direction,c["quality"])
    return out


def trade(rows, index, direction, stop_pct, friction_pct=0.14, horizon=16):
    # Signal observed at end of current 15m; enter at NEXT bar open.
    if index+1>=len(rows):
        return None
    entry=rows[index+1]["open"]
    if entry<=0:
        return None
    s=1 if direction=="LONG" else -1
    stop=entry*(1-s*stop_pct/100)
    tp=entry*(1+s*stop_pct*2/100)
    end=min(index+horizon,len(rows)-1)
    if end<index+1:
        return None
    exit_price=rows[end]["close"]
    exit_kind="TIME"
    exit_idx=end
    for j in range(index+1,end+1):
        candle=rows[j]
        hit_stop=candle["low"]<=stop if s==1 else candle["high"]>=stop
        hit_tp=candle["high"]>=tp if s==1 else candle["low"]<=tp
        if hit_stop:
            exit_price=stop;exit_kind="STOP";exit_idx=j;break
        if hit_tp:
            exit_price=tp;exit_kind="TP";exit_idx=j;break
    gross_pct=s*(exit_price/entry-1)*100
    return {"end_index":exit_idx,"net_r":(gross_pct-friction_pct)/stop_pct,
            "exit":exit_kind}


def simulate(rows_by_tf, asset, start_ms, finish_ms, cost=0.14):
    ts={k:[r["open_time_ms"] for r in v] for k,v in rows_by_tf.items()}
    bars=rows_by_tf["15m"]
    split_ms=start_ms+int((finish_ms-start_ms)*0.7)
    last_end={k:-1 for k in MODES}
    all_trades={k:[] for k in MODES}
    missing=0
    for i in range(len(bars)-1):
        asof=bars[i]["open_time_ms"]+BAR["15m"]
        if asof<start_ms or asof>=finish_ms:
            continue
        frames={tf:frame_at(rows_by_tf[tf],ts[tf],asof,tf)
            for tf in ("4h","1h","15m")}
        if any(v is None or v.get("status")!="OK" for v in frames.values()):
            missing+=1
            continue
        choices=signals(frames,asset)
        atr=frames["1h"]["indicators"].get("atr_pct") or 0
        stop_pct=max(0.5,min(3.0,1.25*float(atr)))
        for name,signal in choices.items():
            if signal is None or i<=last_end[name]:
                continue
            outcome=trade(bars,i,signal[0],stop_pct,cost)
            if outcome is None:
                continue
            last_end[name]=outcome["end_index"]
            all_trades[name].append({"asset":asset,
                "entry_time_ms":bars[i+1]["open_time_ms"],
                "phase":"validation" if asof>=split_ms else "development",
                "quality":signal[1],**outcome})
    return all_trades,missing


def metrics(rows):
    if not rows:
        return {"trades":0,"avg_net_r":None,"net_r":0,"win_pct":None,
                "profit_factor":None,"max_drawdown_r":None}
    r=[x["net_r"] for x in rows]
    equity=high=dd=0.
    for v in r:
        equity+=v
        high=max(high,equity)
        dd=max(dd,high-equity)
    gain=sum(v for v in r if v>0)
    loss=-sum(v for v in r if v<0)
    return {"trades":len(r),"avg_net_r":round(statistics.mean(r),4),
        "net_r":round(sum(r),3),"win_pct":round(100*sum(v>0 for v in r)/len(r),1),
        "profit_factor":round(gain/loss,3) if loss else None,
        "max_drawdown_r":round(dd,3)}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--days",type=int,default=45)
    ap.add_argument("--assets",nargs="+",default=["BTC","ETH","XAU","AAVE"])
    ap.add_argument("--cost-pct",type=float,default=0.14)
    ap.add_argument("--max-pages",type=int,default=600)
    ap.add_argument("--output",default="historical_normal_result.json")
    args=ap.parse_args()
    if not 14<=args.days<=365 or not 0<=args.cost_pct<=3:
        ap.error("invalid history window or cost")
    now=datetime.now(timezone.utc).replace(second=0,microsecond=0)
    t_end=int(now.timestamp()*1000)
    t_start=int((now-timedelta(days=args.days)).timestamp()*1000)
    warm=int((now-timedelta(days=args.days+39)).timestamp()*1000)
    outputs={}
    errors={}
    results={mode:[] for mode in MODES}
    with requests.Session() as session:
        for asset in args.assets:
            if asset not in ASSETS or asset in config.DISABLED_ENTRY_ASSETS:
                ap.error("invalid/disabled asset: "+asset)
            data={}
            try:
                for tf in ("4h","1h","15m"):
                    data[tf]=fetch(session,ASSETS[asset]["okx_swap"],tf,
                        warm,t_end,max_pages=args.max_pages)
                    print("HISTORY_LOADED",asset,tf,len(data[tf]),flush=True)
                trades,missing=simulate(data,asset,t_start,t_end,args.cost_pct)
            except (RuntimeError,requests.RequestException) as exc:
                errors[asset]=str(exc)[:200]
                print("HISTORY_FAILED",asset,errors[asset],flush=True)
                continue
            outputs[asset]={"missing_bars":missing,
                "signals":{k:len(trades[k]) for k in MODES}}
            for k in MODES:
                results[k].extend(trades[k])
    report={"status":"RESEARCH_ONLY" if not errors else "PARTIAL" if outputs else "DATA_UNAVAILABLE","orders_possible":False,
        "data_source":"OKX_LIVE_PUBLIC_SWAP_HISTORY_NOT_DEMO",
        "window_days":args.days,"asof_utc":now.isoformat(),
        "friction_assumption_pct_round_trip":args.cost_pct,
        "execution_assumptions":"Next-15m open; 1.25x 1H ATR stop (0.5%-3%); 2R target; 4h timeout; stop first on simultaneous hits",
        "not_modeled":"LLM, live news/macro, portfolio risk, liquidity, FOK, bid/ask, funding, exchange differences",
        "assets":outputs,"data_errors":errors,
        "strategies":{m:{phase:metrics(sorted((x for x in results[m] if x["phase"]==phase),
                          key=lambda v:v["entry_time_ms"]))
                 for phase in ("development","validation")} for m in MODES}}
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("ASTRA_HISTORY_RESULT="+json.dumps(report,ensure_ascii=False),flush=True)


if __name__=="__main__":
    try:
        main()
    except (RuntimeError,requests.RequestException) as exc:
        print("ASTRA_HISTORY_RESULT="+json.dumps({"status":"DATA_UNAVAILABLE",
            "reason":str(exc)[:240],"orders_possible":False}),flush=True)
        raise SystemExit(2)

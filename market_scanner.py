#!/usr/bin/env python3
"""ASTRA cross-asset market scanner — passive, zero-token, shadow-only.

The scanner reuses already-fetched decision packages. It makes no network calls,
does not choose the live trading universe, and cannot place orders. Its job is to
rank where market activity looks most interesting so we can later validate
whether cross-asset selection adds edge.
"""
import json
import math
import threading
from datetime import datetime, timezone
from pathlib import Path

import config

ORDER_CAPABILITY=False
MODEL_CALL_CAPABILITY=False

LOCK=threading.RLock()
STATE=Path(config.STATE_DIR)/"market_scanner_state.json"

def _now():
    return datetime.now(timezone.utc)

def _parse_ts(x):
    try:return datetime.fromisoformat(str(x or "").replace("Z","+00:00"))
    except Exception:return None

def _num(x,default=None):
    try:return float(x)
    except Exception:return default

def _load():
    try:
        x=json.loads(STATE.read_text(encoding="utf-8"))
        return x if isinstance(x,dict) else {}
    except Exception:
        return {}

def _save(x):
    STATE.parent.mkdir(parents=True,exist_ok=True)
    tmp=STATE.with_name(f"{STATE.name}.{threading.get_ident()}.{int(_now().timestamp()*1_000_000)}.tmp")
    tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding="utf-8")
    tmp.replace(STATE)

def _spread_pct(perp):
    bid=_num((perp or {}).get("bid_price"));ask=_num((perp or {}).get("ask_price"))
    if bid is None or ask is None or bid<=0 or ask<bid:return None
    mid=(bid+ask)/2.0
    return ((ask-bid)/mid*100.0) if mid>0 else None

def _frame(market,tf):
    return (((market or {}).get("multi_timeframe") or {}).get("frames") or {}).get(tf) or {}

def observe(package):
    if not config.MARKET_SCANNER_ENABLED:
        return {"status":"DISABLED","order_capability":False,"model_call_capability":False}
    p=package or {}
    asset=str(p.get("asset") or "").upper()
    if not asset:
        return {"status":"IGNORED","reason":"NO_ASSET"}
    market=((p.get("decision_context") or {}).get("market") or {})
    spot=market.get("spot") or {}
    perp=market.get("perp_okx") or {}
    f15=_frame(market,"15m")
    f1=_frame(market,"1h")
    f4=_frame(market,"4h")

    row={
        "asset":asset,
        "observed_at_utc":_now().isoformat(),
        "price":_num(spot.get("price") or perp.get("last_price")),
        "change_1h_pct":_num((spot.get("changes_pct") or {}).get("1h")),
        "change_4h_pct":_num((spot.get("changes_pct") or {}).get("4h")),
        "change_24h_pct":_num((spot.get("changes_pct") or {}).get("24h")),
        "atr_pct":_num((spot.get("indicators") or {}).get("atr_pct")),
        "rsi14":_num((spot.get("indicators") or {}).get("rsi14")),
        "trend":str((spot.get("regimes") or {}).get("trend") or "UNKNOWN"),
        "momentum":str((spot.get("regimes") or {}).get("momentum") or "UNKNOWN"),
        "book_imbalance":_num((spot.get("order_book") or {}).get("imbalance")),
        "buy_sell_ratio":_num((spot.get("trade_flow") or {}).get("buy_sell_ratio")),
        "spread_pct":_spread_pct(perp),
        "funding_rate":_num(perp.get("funding_rate")),
        "open_interest_contracts":_num(perp.get("open_interest_contracts")),
        "volume_ratio_15m":_num((f15.get("volume") or {}).get("ratio_to_avg20")),
        "volume_ratio_1h":_num((f1.get("volume") or {}).get("ratio_to_avg20")),
        "trend_4h":str((f4.get("regimes") or {}).get("trend") or "UNKNOWN"),
        "data_quality":str((market.get("data_quality") or {}).get("status") or "UNKNOWN"),
        "strategy_mode":str(p.get("strategy_mode") or "NORMAL").upper(),
    }
    with LOCK:
        state=_load()
        state[asset]=row
        _save(state)
    return {"status":"OK","asset":asset,"order_capability":False,"model_call_capability":False}

def _fresh_rows():
    cutoff=float(config.MARKET_SCANNER_STALE_SECONDS)
    now=_now()
    out=[]
    with LOCK:
        for row in _load().values():
            if not isinstance(row,dict):continue
            ts=_parse_ts(row.get("observed_at_utc"))
            if not ts:continue
            age=(now-ts).total_seconds()
            if age<=cutoff:
                x=dict(row);x["age_seconds"]=round(age,1);out.append(x)
    return out

def _median(xs):
    vals=sorted(float(x) for x in xs if isinstance(x,(int,float)))
    if not vals:return 0.0
    n=len(vals)
    return vals[n//2] if n%2 else (vals[n//2-1]+vals[n//2])/2.0

def _opportunity_score(row,median4):
    score=50.0
    reasons=[]

    # Activity/volatility: reward tradable movement, not absolute direction.
    c1=abs(_num(row.get("change_1h_pct"),0.0) or 0.0)
    c4=abs(_num(row.get("change_4h_pct"),0.0) or 0.0)
    score+=min(10.0,c1*5.0)+min(10.0,c4*1.5)
    if c1>=0.35:reasons.append("ACTIVE_1H")
    if c4>=1.0:reasons.append("ACTIVE_4H")

    vr=max(_num(row.get("volume_ratio_15m"),0.0) or 0.0,_num(row.get("volume_ratio_1h"),0.0) or 0.0)
    if vr>=1.0:
        score+=min(10.0,(vr-1.0)*12.0+2.0);reasons.append("VOLUME_EXPANSION")

    spread=_num(row.get("spread_pct"))
    if spread is None:
        score-=4.0;reasons.append("SPREAD_UNKNOWN")
    elif spread<=0.03:
        score+=8.0;reasons.append("TIGHT_SPREAD")
    elif spread<=0.08:
        score+=4.0
    elif spread>0.12:
        score-=12.0;reasons.append("WIDE_SPREAD")

    imb=abs(_num(row.get("book_imbalance"),0.0) or 0.0)
    if imb>=0.12:
        score+=min(6.0,imb*18.0);reasons.append("ORDERBOOK_IMBALANCE")

    ratio=_num(row.get("buy_sell_ratio"))
    if ratio is not None and ratio>0:
        flow=abs(math.log(max(0.05,min(20.0,ratio))))
        if flow>=0.14:
            score+=min(6.0,flow*7.0);reasons.append("AGGRESSIVE_FLOW")

    c4signed=_num(row.get("change_4h_pct"))
    if c4signed is not None and row.get("asset")!="XAU":
        rs=c4signed-median4
        if abs(rs)>=0.5:
            score+=min(8.0,abs(rs)*2.0);reasons.append("RELATIVE_STRENGTH" if rs>0 else "RELATIVE_WEAKNESS")

    if row.get("data_quality")=="FAILED":
        score-=30.0;reasons.append("DATA_FAILED")
    elif row.get("data_quality")=="PARTIAL":
        score-=8.0;reasons.append("DATA_PARTIAL")

    return max(0.0,min(100.0,score)),reasons

def summary():
    if not config.MARKET_SCANNER_ENABLED:
        return {"status":"DISABLED","ranking":[],"order_capability":False,"model_call_capability":False}
    rows=_fresh_rows()
    crypto4=[_num(x.get("change_4h_pct")) for x in rows if x.get("asset")!="XAU"]
    med4=_median([x for x in crypto4 if x is not None])
    ranked=[]
    for row in rows:
        score,reasons=_opportunity_score(row,med4)
        x=dict(row)
        x["opportunity_score"]=round(score,2)
        x["scanner_reasons"]=reasons
        c4=_num(row.get("change_4h_pct"))
        x["relative_strength_4h_vs_crypto_median_pct"]=round(c4-med4,4) if c4 is not None and row.get("asset")!="XAU" else None
        ranked.append(x)
    ranked.sort(key=lambda x:(x["opportunity_score"],-(x.get("spread_pct") or 999)),reverse=True)
    return {
        "status":"OK",
        "generated_at_utc":_now().isoformat(),
        "fresh_assets":len(ranked),
        "crypto_median_change_4h_pct":round(med4,4),
        "ranking":ranked[:max(1,int(config.MARKET_SCANNER_TOP_N))],
        "all":ranked,
        "order_capability":False,
        "model_call_capability":False,
        "note":"Passive ranking only; it does not alter the live trade universe.",
    }

if __name__=="__main__":
    print(json.dumps(summary(),ensure_ascii=False,indent=2))

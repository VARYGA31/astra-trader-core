#!/usr/bin/env python3
"""Dynamic, shadow-only DeFi universe selection from public OKX data.

This module never places orders and never calls OpenAI. It only chooses which
configured DeFi swaps are liquid enough to deserve shadow training.
"""
import json, math
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests

import config
from asset_map import ASSETS

OKX=config.OKX_BASE_URL
CACHE=Path(config.STATE_DIR)/"defi_lab_universe.json"
UA={"User-Agent":"ASTRA-DeFi-Lab/3.0"}

def now():
    return datetime.now(timezone.utc)

def _num(x):
    try: return float(x)
    except Exception: return None

def _get(path,params=None):
    r=requests.get(OKX+path,params=params,headers=UA,timeout=15)
    r.raise_for_status()
    d=r.json()
    if str(d.get("code","0"))!="0":
        raise RuntimeError("OKX:"+str(d.get("msg") or d.get("code")))
    return d.get("data") or []

def _load_cache():
    try:
        x=json.loads(CACHE.read_text(encoding="utf-8"))
        ts=datetime.fromisoformat(str(x.get("generated_at_utc")).replace("Z","+00:00"))
        age=(now()-ts).total_seconds()/60.0
        if age<float(config.DEFI_LAB_UNIVERSE_REFRESH_MINUTES):
            return x
    except Exception:
        pass
    return None

def _save(x):
    try:
        CACHE.parent.mkdir(parents=True,exist_ok=True)
        tmp=CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding="utf-8")
        tmp.replace(CACHE)
    except Exception:
        pass

def refresh(force=False):
    if not force:
        cached=_load_cache()
        if cached:
            return cached

    instruments=_get("/api/v5/public/instruments",{"instType":"SWAP"})
    tickers=_get("/api/v5/market/tickers",{"instType":"SWAP"})
    inst_by={str(x.get("instId")):x for x in instruments}
    tick_by={str(x.get("instId")):x for x in tickers}

    rows=[]
    unavailable=[]
    for asset in config.DEFI_LAB_WATCHLIST:
        cfg=ASSETS.get(asset) or {}
        inst=str(cfg.get("okx_swap") or "")
        if not inst:
            unavailable.append({"asset":asset,"reason":"NO_INSTRUMENT_MAPPING"})
            continue
        meta=inst_by.get(inst)
        tick=tick_by.get(inst)
        if not meta:
            unavailable.append({"asset":asset,"instrument":inst,"reason":"NOT_LISTED_AS_SWAP"})
            continue
        if str(meta.get("state") or "").lower()!="live":
            unavailable.append({"asset":asset,"instrument":inst,"reason":"NOT_LIVE","state":meta.get("state")})
            continue
        if not tick:
            unavailable.append({"asset":asset,"instrument":inst,"reason":"NO_TICKER"})
            continue

        last=_num(tick.get("last")); bid=_num(tick.get("bidPx")); ask=_num(tick.get("askPx"))
        if not last or not bid or not ask or ask<bid:
            unavailable.append({"asset":asset,"instrument":inst,"reason":"BAD_QUOTE"})
            continue
        mid=(bid+ask)/2.0
        spread=((ask-bid)/mid*100.0) if mid else 999.0
        if spread>float(config.DEFI_LAB_MAX_SPREAD_PCT):
            unavailable.append({
                "asset":asset,"instrument":inst,"reason":"SPREAD_TOO_WIDE",
                "spread_pct":round(spread,5),
            })
            continue

        vol_ccy=_num(tick.get("volCcy24h"))
        vol_contracts=_num(tick.get("vol24h"))
        # volCcy24h semantics vary by derivatives instrument; use it when
        # available and fall back to contracts*last only for ranking.
        notional_proxy=(vol_ccy*last) if vol_ccy is not None else ((vol_contracts or 0.0)*last)
        liquidity_score=math.log10(max(1.0,notional_proxy))-spread*8.0
        rows.append({
            "asset":asset,
            "instrument":inst,
            "last":last,
            "bid":bid,
            "ask":ask,
            "spread_pct":round(spread,5),
            "volume_proxy_usd":round(notional_proxy,2),
            "liquidity_score":round(liquidity_score,4),
            "state":"live",
        })

    rows.sort(key=lambda x:(x["liquidity_score"],x["volume_proxy_usd"]),reverse=True)
    selected=rows[:max(1,int(config.DEFI_LAB_TOP_N))]
    out={
        "status":"OK",
        "generated_at_utc":now().isoformat(),
        "watchlist":list(config.DEFI_LAB_WATCHLIST),
        "selected_assets":[x["asset"] for x in selected],
        "selected":selected,
        "eligible":rows,
        "unavailable":unavailable,
    }
    _save(out)
    return out

def cached_summary():
    try:
        x=json.loads(CACHE.read_text(encoding="utf-8"))
        return x if isinstance(x,dict) else {"status":"NO_DATA","selected_assets":[]}
    except Exception:
        return {"status":"NO_DATA","selected_assets":[]}

def summary():
    try:
        return refresh(False)
    except Exception as e:
        cached=None
        try: cached=json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception: pass
        if cached:
            cached=dict(cached)
            cached["status"]="STALE"
            cached["refresh_error"]=str(e)
            return cached
        return {"status":"FAILED","error":str(e),"selected_assets":[]}

if __name__=="__main__":
    print(json.dumps(summary(),ensure_ascii=False,indent=2))

#!/usr/bin/env python3
"""Active trading universe for ASTRA.

NORMAL = core crypto + optional XAU + a dynamic top-N DeFi set chosen from
public OKX liquidity/spread data.
MICRO remains intentionally limited to BTC/ETH/GRAM.
"""
import config
import defi_universe

def _dedupe(xs):
    out=[]
    seen=set()
    for x in xs:
        x=str(x or "").upper()
        if x and x not in seen:
            seen.add(x); out.append(x)
    return out

def normal_assets(universe=None):
    assets=list(config.NORMAL_CORE_ASSETS)

    if config.NORMAL_GOLD_TRADING_ENABLED:
        assets.append("XAU")

    if config.NORMAL_DEFI_TRADING_ENABLED:
        u=universe if isinstance(universe,dict) else defi_universe.summary()
        eligible=[]
        for row in (u.get("eligible") or []):
            asset=str(row.get("asset") or "").upper()
            try: spread=float(row.get("spread_pct"))
            except Exception: continue
            if (
                asset in set(config.DEFI_TRADE_WATCHLIST)
                and spread<=float(config.DEFI_TRADE_MAX_SPREAD_PCT)
            ):
                eligible.append(row)
        eligible.sort(
            key=lambda r:(float(r.get("liquidity_score") or -999),float(r.get("volume_proxy_usd") or 0)),
            reverse=True,
        )
        assets.extend(str(x.get("asset")).upper() for x in eligible[:max(0,int(config.NORMAL_DEFI_TOP_N))])

    return tuple(_dedupe(assets))

def assets_for_mode(mode,universe=None):
    mode=str(mode or "NORMAL").upper()
    if mode=="MICRO":
        return tuple(config.MICRO_ALLOWED_ASSETS)
    if mode=="PAUSED":
        return tuple()
    return normal_assets(universe)

def summary(universe=None):
    u=universe if isinstance(universe,dict) else None
    normal=normal_assets(u)
    return {
        "normal_assets":list(normal),
        "micro_assets":list(config.MICRO_ALLOWED_ASSETS),
        "gold_enabled":bool(config.NORMAL_GOLD_TRADING_ENABLED),
        "defi_enabled":bool(config.NORMAL_DEFI_TRADING_ENABLED),
        "defi_active":[x for x in normal if x in set(config.DEFI_TRADE_WATCHLIST)],
        "defi_top_n":int(config.NORMAL_DEFI_TOP_N),
    }

#!/usr/bin/env python3
"""Active trading universe for ASTRA.

NORMAL = core crypto + optional XAU + a dynamic top-N DeFi set chosen from
public OKX liquidity/spread data.
MICRO remains intentionally limited to BTC/ETH/GRAM.
"""
import config
import defi_universe
from okx_demo_adapter import OKXDemoAdapter

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
        # Never promote stale public liquidity data into live tradability.
        # On refresh failure, keep core assets but fail closed for DeFi.
        source_rows=[] if u.get("status") in {"STALE","FAILED"} else (u.get("eligible") or [])
        for row in source_rows:
            asset=str(row.get("asset") or "").upper()
            try: spread=float(row.get("spread_pct"))
            except Exception: continue
            if not (
                asset in set(config.DEFI_TRADE_WATCHLIST)
                and spread<=float(config.DEFI_TRADE_MAX_SPREAD_PCT)
            ):
                continue
            if str(config.EXECUTION_MODE).lower()=="okx_demo":
                try:
                    tradability=OKXDemoAdapter().account_tradability(asset)
                except Exception:
                    continue
                if not tradability.get("available"):
                    continue
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
    # Preserve the existing live selection path exactly. Read its cached
    # public-data evidence only after selection, for passive diagnostics.
    normal=normal_assets(universe)
    u=universe if isinstance(universe,dict) else (
        defi_universe.cached_summary() if config.NORMAL_DEFI_TRADING_ENABLED else None
    )
    active=set(normal)
    eligible={str(r.get("asset") or "").upper():r for r in ((u or {}).get("eligible") or [])}
    unavailable={str(r.get("asset") or "").upper():r for r in ((u or {}).get("unavailable") or [])}
    selection={}
    for asset in config.DEFI_TRADE_WATCHLIST:
        row=eligible.get(asset)
        denied=unavailable.get(asset)
        if asset in active:
            reason="ACTIVE"
        elif denied:
            reason=str(denied.get("reason") or "PUBLIC_INSTRUMENT_UNAVAILABLE")
        elif row:
            reason=("TRADE_SPREAD_TOO_WIDE" if float(row.get("spread_pct") or 0)>
                    float(config.DEFI_TRADE_MAX_SPREAD_PCT) else "ACCOUNT_OR_TOP_N_FILTER")
        else:
            reason="NOT_IN_ELIGIBLE_UNIVERSE"
        selection[asset]={
            "active":asset in active,
            "reason":reason,
            "spread_pct":(row or denied or {}).get("spread_pct"),
            "instrument":(row or denied or {}).get("instrument"),
        }
    return {
        "normal_assets":list(normal),
        "micro_assets":list(config.MICRO_ALLOWED_ASSETS),
        "gold_enabled":bool(config.NORMAL_GOLD_TRADING_ENABLED),
        "defi_enabled":bool(config.NORMAL_DEFI_TRADING_ENABLED),
        "defi_active":[x for x in normal if x in set(config.DEFI_TRADE_WATCHLIST)],
        "defi_top_n":int(config.NORMAL_DEFI_TOP_N),
        # Diagnostics only: does not participate in universe selection.
        "defi_selection":{
            "status":(u or {}).get("status","DISABLED"),
            "generated_at_utc":(u or {}).get("generated_at_utc"),
            "refresh_error":str((u or {}).get("refresh_error") or "")[:160] or None,
            "assets":selection,
        },
    }

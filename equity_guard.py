#!/usr/bin/env python3
"""Conservative mark-to-market demo equity for entry risk decisions.

No order authority. Missing account data blocks NEW entries; position exits
remain entirely independent of this module.
"""
import json
import math
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import config

BASELINE = Path(config.STATE_DIR) / "equity_guard_daily_baseline.json"
LOCK = threading.RLock()
_cached = None
_cached_until = 0.0


def _daily_change(total_eq, day):
    try:
        data=json.loads(BASELINE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        data={}
    if data.get("date_utc") != day:
        data={"date_utc":day,"starting_total_eq":total_eq}
        BASELINE.parent.mkdir(parents=True,exist_ok=True)
        tmp=BASELINE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data),encoding="utf-8")
        tmp.replace(BASELINE)
    return total_eq-float(data["starting_total_eq"])


def snapshot(ledger, provider=None, now_seconds=None, unrealized_pnl=0.0):
    """Return verified, conservative equity or a fail-closed result.

    ``min`` avoids raising the bot's risk budget on outside credits/funding.
    OKX totalEq already marks positions to market; never add UPL again.
    The daily high-water baseline survives worker redeploys on the volume.
    """
    global _cached, _cached_until
    now_seconds=time.monotonic() if now_seconds is None else now_seconds
    with LOCK:
        try:
            upl=float(unrealized_pnl)
            if not math.isfinite(upl):
                raise ValueError("NONFINITE_UPL")
        except (TypeError,ValueError):
            return {"verified":False,"reason":"OKX_POSITION_UPL_UNAVAILABLE"}
        if provider is None and _cached is not None and now_seconds < _cached_until:
            current=dict(_cached)
            current["equity"]=min(float(current["equity"]),float(ledger["equity"])+min(0.0,upl))
            current["daily_pnl"]=min(float(current["daily_pnl"]),float(ledger["daily_pnl"])+min(0.0,upl))
            return current
        try:
            if provider is None:
                from okx_demo_adapter import OKXDemoAdapter
                response=OKXDemoAdapter().balance()
            else:
                response=provider()
            data=(response.get("data") or [])[0]
            total_eq=float(data["totalEq"])
            ledger_eq=float(ledger["equity"])
            if not all(math.isfinite(x) and x>0 for x in (total_eq,ledger_eq)):
                raise ValueError("INVALID_EQUITY")
            if ledger_eq+min(0.0,upl)<=0:
                raise ValueError("EXHAUSTED_EQUITY")
            day=datetime.now(timezone.utc).date().isoformat()
            today_change=_daily_change(total_eq,day)
            result={
                "verified":True,
                "equity":min(total_eq,ledger_eq+min(0.0,upl)),
                "total_eq":total_eq,
                "ledger_equity":ledger_eq,
                "daily_pnl":min(float(ledger["daily_pnl"])+min(0.0,upl),today_change),
                "account_daily_change":today_change,
                "unrealized_pnl_usd":upl,
                "source":"OKX_TOTAL_EQ_CONSERVATIVE",
            }
            if provider is None:
                _cached=result
                _cached_until=now_seconds+15.0
            return result
        except Exception as exc:
            # Do not fall back to realized-only equity for new orders.
            _cached=None
            _cached_until=0.0
            return {"verified":False,"reason":"OKX_EQUITY_UNAVAILABLE",
                    "error_type":type(exc).__name__}

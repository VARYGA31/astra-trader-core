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


def _operator_demo_balance_adjustment(day,total_eq,raw_day_change,ledger,upl,exchange_flat):
    """One-time explicit operator accounting adjustment, NOT an OKX transfer proof.

    Only in the approved UTC day, in demo, while ALL exchange positions are
    independently verified flat; never expands entry equity/drawdown budget.
    The locked offset is written once and all subsequent day changes are
    measured relative to it, including new realized/unrealized trade losses.
    """
    try:
        state=json.loads(BASELINE.read_text(encoding="utf-8"))
        if state.get("date_utc")!=day:
            return raw_day_change,None
        if config.EXECUTION_MODE!="okx_demo":
            return raw_day_change,None
        approved=state.get("operator_demo_balance_ack")
        if isinstance(approved,dict) and approved.get("date_utc")==day:
            offset=float(approved["offset_usd"])
            if not math.isfinite(offset):
                return raw_day_change,None
            return raw_day_change-offset,approved
        if (config.EXECUTION_MODE!="okx_demo"
            or config.OKX_DEMO_BALANCE_CHANGE_ACK_DATE_UTC!=day
            or exchange_flat is not True
            or abs(upl)>1e-8):
            return raw_day_change,None
        initial=float(ledger["initial_equity"])
        ledger_eq=float(ledger["equity"])
        realized_today=float(ledger["daily_pnl"])
        if not all(math.isfinite(x) for x in (initial,ledger_eq,realized_today)):
            return raw_day_change,None
        if (initial<=0 or total_eq+1e-8<ledger_eq
            or realized_today<=-(initial*config.DAILY_LOSS_LIMIT_PCT)
            or raw_day_change>=realized_today-max(0.01,initial*0.001)):
            return raw_day_change,None
        offset=raw_day_change-realized_today
        approved={
            "date_utc":day,"offset_usd":round(offset,8),
            "acknowledged_at_utc":datetime.now(timezone.utc).isoformat(),
            "source":"OPERATOR_ACK_DEMO_CASH_MOVE_NOT_EXCHANGE_VERIFIED",
            "exchange_positions_confirmed_flat_at_ack":True,
            "ledger_realized_today_at_ack":round(realized_today,8),
        }
        state["operator_demo_balance_ack"]=approved
        temp=BASELINE.with_name(BASELINE.name+"."+str(threading.get_ident())+".tmp")
        temp.write_text(json.dumps(state,separators=(",",":")),encoding="utf-8")
        temp.replace(BASELINE)
        return raw_day_change-offset,approved
    except (OSError,TypeError,ValueError,KeyError):
        # Never assume a failed acknowledgement succeeded.
        return raw_day_change,None


def snapshot(ledger, provider=None, now_seconds=None, unrealized_pnl=0.0, exchange_flat=False):
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
            accounted_change,balance_ack=_operator_demo_balance_adjustment(
                day,total_eq,today_change,ledger,upl,exchange_flat
            )
            result={
                "verified":True,
                "equity":min(total_eq,ledger_eq+min(0.0,upl)),
                "total_eq":total_eq,
                "ledger_equity":ledger_eq,
                "daily_pnl":min(float(ledger["daily_pnl"])+min(0.0,upl),accounted_change),
                "account_daily_change":today_change,
                "adjusted_account_daily_change":accounted_change,
                "operator_demo_balance_ack_date_utc":(
                    balance_ack.get("date_utc") if balance_ack else None
                ),
                "operator_demo_balance_ack_offset_usd":(
                    balance_ack.get("offset_usd") if balance_ack else None
                ),
                "operator_demo_balance_ack_source":(
                    balance_ack.get("source") if balance_ack else None
                ),
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

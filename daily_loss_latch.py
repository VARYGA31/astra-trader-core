#!/usr/bin/env python3
"""Fail-closed persistent UTC daily-loss latch for NEW entries only.

The latching signal is the same conservative daily PnL already used by
Risk Engine. Crossing the daily drawdown limit blocks new entries until the
next UTC date even if the marked account value later recovers. This module
never cancels exits or alters orders, balances, or trade history.
"""
import json
import math
import threading
from datetime import datetime, timezone
from pathlib import Path
import config

FILE=Path(config.STATE_DIR)/"daily_loss_latch.json"
LOCK=threading.RLock()


def observe(initial_equity, conservative_daily_pnl, asof=None):
    """Return {latched: bool, ...}; storage/data errors fail CLOSED.

    The persisted marker is date-scoped in UTC; an observed breach never
    clears within the same day. A new day starts clean unless PnL is already
    below that day's configured threshold.
    """
    asof=asof or datetime.now(timezone.utc)
    if asof.tzinfo is None:
        return {"latched":True,"reason":"NAIVE_TIME"}
    day=asof.astimezone(timezone.utc).date().isoformat()
    try:
        initial=float(initial_equity)
        pnl=float(conservative_daily_pnl)
        limit=float(config.DAILY_LOSS_LIMIT_PCT)
        if not all(math.isfinite(x) for x in (initial,pnl,limit)) or initial<=0 or not 0<limit<=1:
            raise ValueError("INVALID_RISK_INPUT")
    except (ValueError,TypeError):
        return {"latched":True,"reason":"INVALID_RISK_INPUT"}
    with LOCK:
        try:
            row=json.loads(FILE.read_text(encoding="utf-8"))
            if not isinstance(row,dict) or not isinstance(row.get("date_utc"),str):
                raise ValueError("LATCH_STATE_INVALID")
        except FileNotFoundError:
            row={}
        except (OSError,ValueError,TypeError):
            return {"latched":True,"reason":"LATCH_STATE_UNREADABLE"}
        if row.get("date_utc")>day:
            return {"latched":True,"reason":"LATCH_FUTURE_DATE"}
        if row.get("date_utc")==day and row.get("latched") is True:
            return {"latched":True,"date_utc":day,
                    "reason":"DAILY_LOSS_LIMIT_REACHED",
                    "first_breach_at_utc":row.get("first_breach_at_utc")}
        if pnl>-(initial*limit):
            return {"latched":False,"date_utc":day}
        write={
            "date_utc":day,
            "latched":True,
            "first_breach_at_utc":asof.astimezone(timezone.utc).isoformat(),
            "threshold_usd":round(initial*limit,8),
        }
        try:
            FILE.parent.mkdir(parents=True,exist_ok=True)
            temp=FILE.with_name(FILE.name+"."+str(threading.get_ident())+".tmp")
            temp.write_text(json.dumps(write,separators=(",",":")),encoding="utf-8")
            temp.replace(FILE)
        except OSError:
            return {"latched":True,"reason":"LATCH_PERSIST_FAILED"}
        return {"latched":True,"date_utc":day,
                "reason":"DAILY_LOSS_LIMIT_REACHED",
                "first_breach_at_utc":write["first_breach_at_utc"]}

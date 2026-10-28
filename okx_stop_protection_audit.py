#!/usr/bin/env python3
"""Independent, READ-ONLY OKX demo stop verification.

This file has no trading/order modification calls. It fetches open positions
and pending conditional/OCO algorithms, cross-references coverage and reports
unverified coverage honestly. It never asserts safety when exchange data fails.
Run via a daemon thread; never delay position monitoring/exit worker ticks.
"""
import math
from datetime import datetime, timezone

import config
import okx_position_monitor
from okx_demo_adapter import OKXDemoAdapter


def _positive(value):
    try:
        x=float(value)
        return x if math.isfinite(x) and x>0 else None
    except (TypeError, ValueError):
        return None


def _stop_orders(rows):
    """Flatten conditional/OCO entries, without treating a TP as a stop."""
    out={}
    for row in rows:
        if not isinstance(row,dict):
            continue
        inst=row.get("instId")
        if not inst:
            continue
        for entry in [row]+list(row.get("attachAlgoOrds") or []):
            price=_positive(entry.get("slTriggerPx"))
            if price is None:
                continue
            side=str(entry.get("side") or row.get("side") or "").lower()
            qty=_positive(entry.get("sz") or row.get("sz"))
            ident=str(entry.get("algoId") or entry.get("attachAlgoId") or row.get("algoId") or "")
            key=(inst,ident,price,side)
            out[key]={"stop":price,"qty":qty,"side":side}
    result={}
    for (inst,_,_,_),entry in out.items():
        result.setdefault(inst,[]).append(entry)
    return result


def analyze(exchange,tracked,pending_by_type,complete=True):
    """Pure data processing. UNKNOWN is distinct from verified unprotected."""
    if not isinstance(exchange,dict) or not isinstance(tracked,dict):
        return {"status":"UNKNOWN","reason":"BAD_INPUT","read_only":True}
    items=list(exchange.get("details") or [])
    if not complete:
        return {"status":"UNKNOWN","reason":"PENDING_LIST_INCOMPLETE",
                "open_positions":len(items),"read_only":True}
    if not isinstance(pending_by_type,dict) or not all(
        isinstance(pending_by_type.get(k),list) for k in ("conditional","oco")
    ):
        return {"status":"UNKNOWN","reason":"MISSING_ORDER_TYPE",
                "open_positions":len(items),"read_only":True}
    pending=_stop_orders(pending_by_type["conditional"]+pending_by_type["oco"])
    results=[]
    for p in items:
        asset=str(p.get("asset") or "").upper()
        inst=str(p.get("instId") or "")
        qty=_positive(p.get("qty_contracts"))
        if not asset or not inst or qty is None:
            results.append({"asset":asset or "UNKNOWN","status":"UNKNOWN",
                            "reason":"POSITION_SIZE_UNAVAILABLE"})
            continue
        expected_side="sell" if p.get("side")=="LONG" else "buy" if p.get("side")=="SHORT" else ""
        if not expected_side:
            results.append({"asset":asset,"status":"UNKNOWN","reason":"POSITION_SIDE_UNAVAILABLE"})
            continue
        candidates=pending.get(inst,[])
        matches=[x for x in candidates if not x["side"] or x["side"]==expected_side]
        wrong_side=[x for x in candidates if x["side"] and x["side"]!=expected_side]
        known_size=[x["qty"] for x in matches if x["qty"] is not None]
        unknown_size=any(x["qty"] is None for x in matches)
        coverage=sum(known_size)
        # A TP/SL split can cover a position through multiple attached algos.
        # Quantity is a CONTRACT count. Do not assert full protection if size
        # or trade direction is missing from the exchange's response.
        if not matches:
            status="MISSING_STOP_ALGO"
        elif unknown_size:
            status="UNKNOWN"
        elif coverage + max(1e-12,qty*1e-4) < qty:
            status="PARTIAL_STOP_COVERAGE"
        else:
            status="VERIFIED_ACTIVE_STOP"
        rec=tracked.get(asset) or {}
        planned=_positive(rec.get("stop_loss"))
        visible=[x["stop"] for x in matches]
        # Only detect a larger risk than the original planned stop;
        # trailing to breakeven/favourable stops is not a problem.
        weaker=False
        if planned and visible:
            if expected_side=="sell":
                weaker=any(price<planned*0.997 for price in visible)
            else:
                weaker=any(price>planned*1.003 for price in visible)
        if weaker and status=="VERIFIED_ACTIVE_STOP":
            status="STOP_WORSE_THAN_PLAN"
        results.append({"asset":asset,"status":status,"qty_contracts":qty,
            "known_stop_contracts":round(coverage,10),
            "stop_orders_found":len(matches),"wrong_side_orders_found":len(wrong_side),
            "stop_price_worse_than_plan":weaker,
            "local_trade_record":asset in tracked})
    flags=[x for x in results if x["status"] in {
        "MISSING_STOP_ALGO","PARTIAL_STOP_COVERAGE","STOP_WORSE_THAN_PLAN"}]
    uncertain=[x for x in results if x["status"]=="UNKNOWN"]
    # A positive audit is exchange-observed, not a guarantee of a future fill.
    status="ALERT" if flags else "UNKNOWN" if uncertain else "OK"
    if not items:
        status="NO_OPEN_POSITIONS"
    return {"status":status,"read_only":True,"open_positions":len(items),
        "verified_positions":sum(x["status"]=="VERIFIED_ACTIVE_STOP" for x in results),
        "alert_count":len(flags),"unknown_count":len(uncertain),
        "positions":results,"algo_types_checked":["conditional","oco"]}


def snapshot():
    """Read exchange facts only. Caller runs this outside the trade loop."""
    if config.EXECUTION_MODE!="okx_demo":
        return {"status":"NOT_OKX_DEMO","read_only":True}
    adapter=OKXDemoAdapter()
    exchange=adapter.exchange_active_summary()
    count=int(exchange.get("open_positions") or 0)
    if count==0:
        return analyze(exchange,okx_position_monitor.load(),
                       {"conditional":[],"oco":[]})
    pending={}
    complete=True
    for kind in ("conditional","oco"):
        response=adapter.private_get("/api/v5/trade/orders-algo-pending",
                                    {"ordType":kind,"instType":"SWAP","limit":"100"})
        pending[kind]=response.get("data")
        if not isinstance(pending[kind],list):
            return {"status":"UNKNOWN","reason":"PENDING_ORDERS_NOT_LIST",
                    "open_positions":count,"read_only":True}
        if len(pending[kind])>=100:
            complete=False  # Pagination could hide relevant protective SLs.
    return analyze(exchange,okx_position_monitor.load(),pending,complete)


def safe_snapshot():
    try:
        return {**snapshot(),"checked_at_utc":datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        # Do not print API keys, response bodies or private HTTP errors.
        return {"status":"UNKNOWN","reason":"EXCHANGE_QUERY_FAILED",
                "error_type":type(e).__name__,"read_only":True,
                "checked_at_utc":datetime.now(timezone.utc).isoformat()}

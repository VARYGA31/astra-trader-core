#!/usr/bin/env python3
"""Shadow validator for a possible second simultaneous MICRO position.

This module is intentionally non-executing. It can record a hypothetical second
trade and evaluate the next five minutes from public OKX candles, but it has no
order-routing imports and never calls trade_cycle.execute.
"""
import json
import threading
import time
from pathlib import Path

import requests

import config
from asset_map import ASSETS

FILE=Path(config.STATE_DIR)/"micro_second_shadow.json"
LOCK=threading.RLock()

def _load():
    try:
        rows=json.loads(FILE.read_text(encoding="utf-8"))
        return rows if isinstance(rows,list) else []
    except Exception:
        return []

def _save(rows):
    FILE.parent.mkdir(parents=True,exist_ok=True)
    rows=list(rows)[-max(50,int(config.MICRO_SECOND_SHADOW_MAX_ROWS)):]
    tmp=FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")
    tmp.replace(FILE)

def _num(x):
    try:return float(x)
    except Exception:return None

def _pnl(notional,entry,exit_px,action):
    if action=="LONG":
        return float(notional)*(float(exit_px)-float(entry))/float(entry)
    return float(notional)*(float(entry)-float(exit_px))/float(entry)

def _correlated_same_direction(account,asset,action):
    if not config.BLOCK_BTC_ETH_SAME_DIRECTION or asset not in {"BTC","ETH"}:
        return False
    other="ETH" if asset=="BTC" else "BTC"
    for p in account.get("exchange_positions",[]) or []:
        if str(p.get("asset") or "").upper()==other and str(p.get("side") or "").upper()==action:
            return True
    return False

def consider(package,decision,gate):
    """Record a hypothetical second position. Never submit an order."""
    if not config.MICRO_SECOND_SHADOW_ENABLED:
        return {"status":"SKIPPED","reason":"SECOND_SHADOW_DISABLED"}

    account=(package or {}).get("account_state") or {}
    if int(account.get("open_positions") or 0)<1:
        return {"status":"SKIPPED","reason":"NO_FIRST_POSITION"}

    asset=str((decision or {}).get("asset") or (package or {}).get("asset") or "").upper()
    action=str((decision or {}).get("action") or "").upper()
    if action not in {"LONG","SHORT"}:
        return {"status":"SKIPPED","reason":"NO_TRADE_DECISION"}
    if asset in set(account.get("open_assets") or []):
        return {"status":"SKIPPED","reason":"ASSET_ALREADY_OPEN"}
    if _correlated_same_direction(account,asset,action):
        return {"status":"SKIPPED","reason":"BTC_ETH_SAME_DIRECTION"}

    quality=_num((gate or {}).get("mtf_quality"))
    if quality is None:
        quality=_num(((gate or {}).get("mtf") or {}).get("quality")) or 0.0
    confidence=_num((decision or {}).get("confidence")) or 0.0
    if quality<float(config.MICRO_SECOND_SHADOW_MIN_QUALITY):
        return {"status":"SKIPPED","reason":"SECOND_QUALITY_TOO_LOW","quality":quality}
    if confidence<float(config.MICRO_SECOND_SHADOW_MIN_CONFIDENCE):
        return {"status":"SKIPPED","reason":"SECOND_CONFIDENCE_TOO_LOW","confidence":confidence}

    entry=_num((decision or {}).get("entry"))
    stop=_num((decision or {}).get("stop_loss"))
    tp1=_num((decision or {}).get("take_profit_1"))
    tp2=_num((decision or {}).get("take_profit_2"))
    if not all(x is not None and x>0 for x in (entry,stop,tp1,tp2)):
        return {"status":"SKIPPED","reason":"INVALID_LEVELS"}

    if action=="LONG":
        if not (stop<entry<tp1<tp2):
            return {"status":"SKIPPED","reason":"INVALID_LONG_LEVELS"}
    else:
        if not (stop>entry>tp1>tp2):
            return {"status":"SKIPPED","reason":"INVALID_SHORT_LEVELS"}

    equity=_num(account.get("equity")) or 0.0
    exposure=_num(account.get("current_exposure_usd")) or 0.0
    if equity<=0:
        return {"status":"SKIPPED","reason":"INVALID_EQUITY"}

    stop_dist=abs(entry-stop)/entry
    if stop_dist<=0:
        return {"status":"SKIPPED","reason":"INVALID_STOP_DISTANCE"}

    risk_usd=equity*float(config.MICRO_SECOND_SHADOW_RISK_PCT)
    risk_notional=risk_usd/stop_dist
    position_cap=equity*float(config.MICRO_SECOND_SHADOW_MAX_POSITION_PCT)
    exposure_left=max(0.0,equity*float(config.MICRO_SECOND_SHADOW_TOTAL_EXPOSURE_PCT)-exposure)
    notional=min(risk_notional,position_cap,exposure_left)
    if notional<=0:
        return {"status":"SKIPPED","reason":"NO_SHADOW_EXPOSURE_CAPACITY"}

    mtf=(gate or {}).get("mtf") or {}
    candle=mtf.get("trigger_candle_id")
    key=f"{asset}:{action}:{candle or int(time.time()//60)}"
    now_ms=int(time.time()*1000)
    cost_pct=2.0*(
        float(config.MICRO_FALLBACK_TAKER_FEE_PCT_PER_SIDE)
        + float(config.MICRO_ESTIMATED_SLIPPAGE_PCT_PER_SIDE)
    )

    with LOCK:
        rows=_load()
        if any(r.get("key")==key for r in rows):
            return {"status":"SKIPPED","reason":"DUPLICATE_SHADOW_CANDIDATE","key":key}
        row={
            "key":key,
            "status":"PENDING",
            "asset":asset,
            "action":action,
            "created_at_ms":now_ms,
            "due_at_ms":now_ms+int(config.MICRO_SECOND_SHADOW_HORIZON_SECONDS)*1000,
            "trigger_candle_id":candle,
            "entry":entry,
            "stop_loss":stop,
            "take_profit_1":tp1,
            "take_profit_2":tp2,
            "quality":quality,
            "confidence":confidence,
            "equity_usd":equity,
            "first_position_exposure_usd":exposure,
            "shadow_notional_usd":notional,
            "shadow_risk_usd":notional*stop_dist,
            "estimated_roundtrip_cost_pct":cost_pct,
            "order_capability":False,
        }
        rows.append(row)
        _save(rows)
    return {
        "status":"SHADOW_SECOND_RECORDED",
        "reason":"NO_ORDER_SENT",
        "key":key,
        "asset":asset,
        "action":action,
        "shadow_notional_usd":notional,
        "shadow_risk_usd":notional*stop_dist,
        "order_capability":False,
    }

def _public_candles(asset,limit=20):
    inst=(ASSETS.get(asset) or {}).get("okx_swap")
    if not inst:
        raise RuntimeError(f"NO_OKX_SWAP:{asset}")
    r=requests.get(
        config.OKX_BASE_URL+"/api/v5/market/candles",
        params={"instId":inst,"bar":"1m","limit":str(limit)},
        headers={"x-simulated-trading":"1","User-Agent":"ASTRA-Second-Shadow/1.0"},
        timeout=15,
    )
    r.raise_for_status()
    body=r.json()
    if str(body.get("code"))!="0":
        raise RuntimeError(f"OKX_CANDLES:{body}")
    out=[]
    for x in body.get("data") or []:
        try:
            out.append({
                "ts":int(x[0]),"open":float(x[1]),"high":float(x[2]),
                "low":float(x[3]),"close":float(x[4]),
                "confirmed":str(x[8])=="1" if len(x)>8 else True,
            })
        except Exception:
            continue
    return sorted(out,key=lambda z:z["ts"])

def simulate(record,candles):
    """Conservative 50/50 TP1/TP2 simulation with BE after TP1."""
    action=str(record.get("action") or "").upper()
    entry=float(record["entry"]); stop=float(record["stop_loss"])
    tp1=float(record["take_profit_1"]); tp2=float(record["take_profit_2"])
    notional=float(record["shadow_notional_usd"])
    start=int(record.get("created_at_ms") or 0)
    due=int(record.get("due_at_ms") or 0)

    future=[
        c for c in candles
        if bool(c.get("confirmed",True)) and int(c.get("ts") or 0)>start and int(c.get("ts") or 0)<=due+60000
    ]
    if not future:
        return {"status":"NOT_READY","reason":"NO_CONFIRMED_FUTURE_CANDLES"}

    half=notional/2.0
    gross=0.0
    tp1_taken=False
    remaining=notional
    exit_reason=None
    exit_price=None

    for c in future:
        hi=float(c["high"]); lo=float(c["low"])
        stop_px=entry if tp1_taken else stop

        if action=="LONG":
            stop_hit=lo<=stop_px
            tp1_hit=(not tp1_taken and hi>=tp1)
            tp2_hit=(tp1_taken and hi>=tp2)
        else:
            stop_hit=hi>=stop_px
            tp1_hit=(not tp1_taken and lo<=tp1)
            tp2_hit=(tp1_taken and lo<=tp2)

        if not tp1_taken:
            # Same-candle stop + TP1 path is unknowable from OHLC. Count it
            # conservatively as a stop so the experiment cannot look too good.
            if stop_hit:
                gross+=_pnl(notional,entry,stop,action)
                remaining=0.0; exit_reason="STOP_LOSS"; exit_price=stop
                break
            if tp1_hit:
                gross+=_pnl(half,entry,tp1,action)
                remaining=half
                tp1_taken=True

                # After TP1 the real strategy moves SL to breakeven. If both
                # BE and TP2 fit inside the same candle, choose BE conservatively.
                be_hit=(lo<=entry) if action=="LONG" else (hi>=entry)
                full_tp2=(hi>=tp2) if action=="LONG" else (lo<=tp2)
                if be_hit:
                    gross+=_pnl(remaining,entry,entry,action)
                    remaining=0.0; exit_reason="TP1_THEN_BREAKEVEN"; exit_price=entry
                    break
                if full_tp2:
                    gross+=_pnl(remaining,entry,tp2,action)
                    remaining=0.0; exit_reason="TP1_TP2"; exit_price=tp2
                    break
        else:
            if stop_hit:
                gross+=_pnl(remaining,entry,entry,action)
                remaining=0.0; exit_reason="TP1_THEN_BREAKEVEN"; exit_price=entry
                break
            if tp2_hit:
                gross+=_pnl(remaining,entry,tp2,action)
                remaining=0.0; exit_reason="TP1_TP2"; exit_price=tp2
                break

    if remaining>0:
        final=float(future[-1]["close"])
        gross+=_pnl(remaining,entry,final,action)
        exit_reason="TIME_EXIT_AFTER_TP1" if tp1_taken else "TIME_EXIT"
        exit_price=final

    cost=notional*float(record.get("estimated_roundtrip_cost_pct") or 0)/100.0
    net=gross-cost
    risk=float(record.get("shadow_risk_usd") or 0)
    return {
        "status":"EVALUATED",
        "exit_reason":exit_reason,
        "exit_price":exit_price,
        "gross_pnl_usd":round(gross,8),
        "estimated_cost_usd":round(cost,8),
        "net_pnl_usd":round(net,8),
        "net_r":round(net/risk,6) if risk>0 else None,
        "win":net>0,
        "tp1_taken":tp1_taken,
        "candles_evaluated":len(future),
    }

def evaluate_pending(now_ms=None):
    if not config.MICRO_SECOND_SHADOW_ENABLED:
        return {"status":"DISABLED","evaluated":0}
    now_ms=int(time.time()*1000) if now_ms is None else int(now_ms)
    count=0
    with LOCK:
        rows=_load()
        changed=False
        for row in rows:
            if row.get("status")!="PENDING" or int(row.get("due_at_ms") or 0)>now_ms:
                continue
            try:
                result=simulate(row,_public_candles(row.get("asset"),20))
                if result.get("status")=="EVALUATED":
                    row.update(result)
                    row["evaluated_at_ms"]=now_ms
                    changed=True; count+=1
            except Exception as e:
                row["last_eval_error"]=str(e)
                row["last_eval_attempt_ms"]=now_ms
                changed=True
        if changed:
            _save(rows)
    return {"status":"OK","evaluated":count}

def summary():
    with LOCK:
        rows=_load()
    evaluated=[r for r in rows if r.get("status")=="EVALUATED"]
    pending=[r for r in rows if r.get("status")=="PENDING"]
    pnls=[float(r.get("net_pnl_usd") or 0) for r in evaluated]
    wins=sum(1 for x in pnls if x>0)
    losses=sum(1 for x in pnls if x<0)
    gp=sum(x for x in pnls if x>0)
    gl=abs(sum(x for x in pnls if x<0))
    pf=(gp/gl) if gl>0 else (None if gp<=0 else "INF")
    return {
        "status":"OK",
        "pending":len(pending),
        "evaluated":len(evaluated),
        "wins":wins,
        "losses":losses,
        "win_rate_pct":round(wins/len(evaluated)*100.0,2) if evaluated else 0.0,
        "net_pnl_usd":round(sum(pnls),6),
        "profit_factor":round(pf,4) if isinstance(pf,(int,float)) else pf,
        "avg_net_r":round(
            sum(float(r.get("net_r") or 0) for r in evaluated)/len(evaluated),4
        ) if evaluated else None,
        "order_capability":False,
    }

def telegram_text():
    s=summary()
    return "\n".join([
        "🧪 <b>MICRO SECOND-POSITION SHADOW</b>","",
        f"Ожидают оценки: <b>{s['pending']}</b>",
        f"Оценено: <b>{s['evaluated']}</b>",
        f"W/L: <b>{s['wins']}/{s['losses']}</b> · Win rate: <b>{s['win_rate_pct']:.1f}%</b>",
        f"Shadow NET PnL: <b>${s['net_pnl_usd']:.4f}</b>",
        f"Profit factor: <b>{s['profit_factor']}</b> · Avg NET R: <b>{s['avg_net_r']}</b>",
        "Ордеры второй позиции: <b>DISABLED</b>",
    ])

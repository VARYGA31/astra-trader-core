#!/usr/bin/env python3
"""OKX-native microstructure cache for MICRO v2.

Uses public WebSocket books5 + trades. If the stream is not ready, callers can
fall back to REST without blocking the trading worker.
"""
import json, threading, time
from collections import deque

import config
from asset_map import ASSETS

try:
    import websocket
except Exception:
    websocket=None

LOCK=threading.RLock()
THREAD=None
STATE={
    "status":"STOPPED",
    "connected":False,
    "last_error":None,
    "last_message_at":None,
    "assets":{},
}

def _now(): return time.time()

def _asset_for_inst(inst):
    for a in config.MICRO_ALLOWED_ASSETS:
        if (ASSETS.get(a) or {}).get("okx_swap")==inst:
            return a
    return None

def _asset_state(asset):
    return STATE["assets"].setdefault(asset,{
        "book":None,
        "book_ts":0.0,
        "trades":deque(maxlen=max(50,int(config.MICRO_WS_TRADE_BUFFER))),
        "trade_ts":0.0,
    })

def _handle_book(asset,row):
    bids=row.get("bids") or []
    asks=row.get("asks") or []
    def notion(xs):
        total=0.0
        for x in xs[:5]:
            try: total += float(x[0])*float(x[1])
            except Exception: pass
        return total
    b=notion(bids); a=notion(asks)
    bid=float(bids[0][0]) if bids else None
    ask=float(asks[0][0]) if asks else None
    imb=(b-a)/(b+a) if b+a else None
    st=_asset_state(asset)
    st["book"]={"bid_notional_top5":b,"ask_notional_top5":a,"imbalance":imb,"bid":bid,"ask":ask}
    st["book_ts"]=_now()

def _handle_trades(asset,rows):
    st=_asset_state(asset)
    now=_now()
    for t in rows:
        try:
            side=str(t.get("side") or "").lower()
            px=float(t.get("px") or 0); sz=float(t.get("sz") or 0)
            if side not in {"buy","sell"} or px<=0 or sz<=0: continue
            st["trades"].append((now,side,px*sz))
        except Exception:
            continue
    st["trade_ts"]=now

def _message(_,raw):
    try:
        msg=json.loads(raw)
    except Exception:
        return
    if msg.get("event") in {"error","notice"}:
        with LOCK:
            STATE["last_error"]=msg
        return
    arg=msg.get("arg") or {}
    inst=arg.get("instId"); channel=arg.get("channel")
    asset=_asset_for_inst(inst)
    if not asset: return
    data=msg.get("data") or []
    with LOCK:
        STATE["last_message_at"]=_now()
        if channel=="books5" and data:
            _handle_book(asset,data[0])
        elif channel=="trades" and data:
            _handle_trades(asset,data)

def _open(ws):
    args=[]
    for asset in config.MICRO_ALLOWED_ASSETS:
        inst=(ASSETS.get(asset) or {}).get("okx_swap")
        if not inst: continue
        args.append({"channel":"books5","instId":inst})
        args.append({"channel":"trades","instId":inst})
    ws.send(json.dumps({"id":"astra-micro-v2","op":"subscribe","args":args},separators=(",",":")))
    with LOCK:
        STATE["status"]="RUNNING"; STATE["connected"]=True; STATE["last_error"]=None

def _close(_,code,msg):
    with LOCK:
        STATE["connected"]=False
        STATE["status"]="RECONNECTING"
        STATE["last_error"]=f"close {code}: {msg}"

def _error(_,err):
    with LOCK:
        STATE["connected"]=False
        STATE["last_error"]=str(err)

def _run():
    if websocket is None:
        with LOCK:
            STATE["status"]="DISABLED"; STATE["last_error"]="websocket-client not installed"
        return
    while True:
        try:
            ws=websocket.WebSocketApp(
                config.OKX_PUBLIC_WS_URL,
                on_open=_open,on_message=_message,on_close=_close,on_error=_error,
            )
            ws.run_forever(ping_interval=20,ping_timeout=8)
        except Exception as e:
            with LOCK:
                STATE["connected"]=False; STATE["status"]="RECONNECTING"; STATE["last_error"]=str(e)
        time.sleep(max(1,float(config.MICRO_WS_RECONNECT_SECONDS)))

def ensure_started():
    global THREAD
    if not config.MICRO_WS_ENABLED:
        return {"status":"DISABLED"}
    with LOCK:
        if THREAD and THREAD.is_alive():
            return health()
        THREAD=threading.Thread(target=_run,name="astra-micro-okx-ws",daemon=True)
        THREAD.start()
    return {"status":"STARTING"}

def snapshot(asset):
    asset=str(asset or "").upper()
    with LOCK:
        st=STATE["assets"].get(asset)
        if not st or not st.get("book"):
            return {"status":"NOT_READY","source":"OKX_WS"}
        now=_now()
        book_age=now-float(st.get("book_ts") or 0)
        trade_age=now-float(st.get("trade_ts") or 0)
        age=max(book_age,trade_age)
        if (
            not st.get("book_ts") or not st.get("trade_ts")
            or age>float(config.MICRO_WS_STALE_SECONDS)
        ):
            return {
                "status":"STALE","source":"OKX_WS","age_seconds":age,
                "book_age_seconds":book_age,"trade_age_seconds":trade_age,
            }

        cutoff=now-float(config.MICRO_FLOW_WINDOW_SECONDS)
        buy=sell=0.0
        for ts,side,n in list(st.get("trades") or []):
            if ts<cutoff: continue
            if side=="buy": buy+=n
            else: sell+=n
        book=dict(st["book"])
        bid=book.get("bid"); ask=book.get("ask")
        mid=((bid+ask)/2.0) if bid and ask else None
        return {
            "status":"OK",
            "source":"OKX_WS_BOOKS5_TRADES",
            "age_seconds":age,
            "order_book":book,
            "trade_flow":{
                "aggressive_buy_weight":buy,
                "aggressive_sell_weight":sell,
                "buy_sell_ratio":(buy/sell) if sell>0 else (None if buy<=0 else 99.0),
                "window_seconds":float(config.MICRO_FLOW_WINDOW_SECONDS),
            },
            "bid":bid,"ask":ask,
            "spread_pct":((ask-bid)/mid*100.0) if mid and ask>=bid else None,
        }

def health():
    with LOCK:
        return {
            "status":STATE.get("status"),
            "connected":STATE.get("connected"),
            "last_error":STATE.get("last_error"),
            "last_message_at":STATE.get("last_message_at"),
            "assets":{
                a:{
                    "book_age_seconds":(_now()-x.get("book_ts",0)) if x.get("book_ts") else None,
                    "trade_age_seconds":(_now()-x.get("trade_ts",0)) if x.get("trade_ts") else None,
                }
                for a,x in STATE.get("assets",{}).items()
            },
        }

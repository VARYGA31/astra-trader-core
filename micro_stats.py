#!/usr/bin/env python3
"""Persistent MICRO v2 execution funnel and net-edge diagnostics."""
import json, threading
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
import config

FILE=Path(config.STATE_DIR)/"micro_stats.jsonl"
JOURNAL=Path(config.STATE_DIR)/"trade_journal.jsonl"
LOCK=threading.Lock()

def _now(): return datetime.now(timezone.utc)

def _parse(x):
    try:return datetime.fromisoformat(str(x).replace("Z","+00:00"))
    except Exception:return None

def _compact():
    try:
        if FILE.stat().st_size<=float(config.MICRO_STATS_LOG_MAX_MB)*1024*1024:return
        rows=FILE.read_text(encoding="utf-8").splitlines()
        tmp=FILE.with_suffix(".tmp")
        tmp.write_text("\n".join(rows[len(rows)//2:])+"\n",encoding="utf-8")
        tmp.replace(FILE)
    except Exception: pass

def record(package,gate,decision,execution,model_called=False):
    try:
        mtf=gate.get("mtf") or {}
        ex=execution or {}
        eq=ex.get("execution_quality") or (ex.get("trade") or {}).get("execution_quality") or {}
        ne=eq.get("micro_net_edge") or ex.get("micro_net_edge") or {}
        spot=((package or {}).get("decision_context") or {}).get("market",{}).get("spot",{})
        row={
            "timestamp_utc":_now().isoformat(),
            "asset":package.get("asset"),
            "gate_reason":gate.get("reason"),
            "gate_passed":bool(mtf.get("passed")),
            "quality":gate.get("mtf_quality",mtf.get("quality")),
            "direction":gate.get("allowed_direction") or mtf.get("direction"),
            "microstructure_source":spot.get("microstructure_source"),
            "model_called":bool(model_called),
            "model_action":(decision or {}).get("action") if model_called else None,
            "model_confidence":(decision or {}).get("confidence") if model_called else None,
            "execution_status":ex.get("status"),
            "execution_reason":ex.get("reason"),
            "execution_stage":ex.get("stage"),
            "spread_pct":mtf.get("spread_pct"),
            "fee_pct_per_side":ne.get("taker_fee_pct_per_side"),
            "estimated_roundtrip_cost_pct":ne.get("estimated_roundtrip_cost_pct"),
            "cost_r":ne.get("cost_r"),
            "net_tp1_r":ne.get("net_tp1_r"),
            "net_tp2_r":ne.get("net_tp2_r"),
        }
        FILE.parent.mkdir(parents=True,exist_ok=True)
        with LOCK:
            with FILE.open("a",encoding="utf-8") as f:
                f.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")
            _compact()
    except Exception:
        pass

def _rows(hours):
    cutoff=_now()-timedelta(hours=float(hours))
    out=[]
    try:
        with LOCK: lines=FILE.read_text(encoding="utf-8").splitlines()
        for line in lines:
            try:r=json.loads(line)
            except Exception:continue
            dt=_parse(r.get("timestamp_utc"))
            if dt and dt>=cutoff:out.append(r)
    except Exception:pass
    return out

def _closed_trades(hours):
    cutoff=_now()-timedelta(hours=float(hours))
    out=[]; seen=set()
    try: lines=JOURNAL.read_text(encoding="utf-8").splitlines()
    except Exception: return out
    for line in lines:
        try:r=json.loads(line)
        except Exception:continue
        if r.get("event")!="OKX_POSITION_CLOSED":continue
        if str(r.get("strategy_mode") or "").upper()!="MICRO":continue
        dt=_parse(r.get("timestamp_utc"))
        if not dt or dt<cutoff:continue
        key=r.get("close_event_id") or (str(r.get("asset"))+":"+str(r.get("order_id"))+":"+str(r.get("opened_at_utc")))
        if key in seen:continue
        seen.add(key);out.append(r)
    return out

def summary(hours=None):
    hours=float(hours or config.MICRO_STATS_DEFAULT_HOURS)
    rows=_rows(hours)
    blockers=Counter();actions=Counter();execs=Counter();sources=Counter();assets=Counter()
    calls=waits=trade_decisions=opened=fok=net_reject=0
    spreads=[];costrs=[];net1=[];net2=[]
    for r in rows:
        assets[str(r.get("asset") or "?")]+=1
        sources[str(r.get("microstructure_source") or "?")]+=1
        if not r.get("model_called"): blockers[str(r.get("gate_reason") or "UNKNOWN")]+=1
        else:
            calls+=1
            a=str(r.get("model_action") or "?");actions[a]+=1
            if a=="WAIT":waits+=1
            if a in {"LONG","SHORT"}:trade_decisions+=1
        status=str(r.get("execution_status") or "")
        reason=str(r.get("execution_reason") or "")
        if status=="OKX_DEMO_OPENED":opened+=1
        if reason=="ENTRY_FOK_NOT_FILLED":fok+=1
        if reason in {"MICRO_NET_EDGE_TOO_LOW","POST_FILL_NET_EDGE_TOO_LOW"}:net_reject+=1
        if reason:execs[reason]+=1
        for key,arr in (("spread_pct",spreads),("cost_r",costrs),("net_tp1_r",net1),("net_tp2_r",net2)):
            try:
                v=float(r.get(key))
                arr.append(v)
            except Exception:pass
    avg=lambda x: round(sum(x)/len(x),5) if x else None
    closed=_closed_trades(hours)
    pnls=[]; fees=[]
    for x in closed:
        try:pnls.append(float(x.get("pnl_usd") or 0))
        except Exception:pass
        try:fees.append(float(x.get("fee_usd") or 0))
        except Exception:pass
    wins=sum(1 for x in pnls if x>0); losses=sum(1 for x in pnls if x<0)
    return {
        "status":"OK","hours":hours,"checks":len(rows),"by_asset":dict(assets),
        "microstructure_sources":dict(sources),"blockers":dict(blockers.most_common()),
        "model_calls":calls,"model_actions":dict(actions),"model_waits":waits,
        "model_trade_decisions":trade_decisions,"opened_trades":opened,
        "fok_not_filled":fok,"net_edge_rejections":net_reject,
        "execution_rejections":dict(execs.most_common()),
        "avg_spread_pct":avg(spreads),"avg_cost_r":avg(costrs),
        "avg_net_tp1_r":avg(net1),"avg_net_tp2_r":avg(net2),
        "closed_trades":len(pnls),"wins":wins,"losses":losses,
        "win_rate_pct":round(wins/len(pnls)*100.0,2) if pnls else 0.0,
        "realized_net_pnl_usd":round(sum(pnls),6),
        "realized_fee_usd":round(sum(fees),6),
    }

def telegram_text(hours=None):
    s=summary(hours)
    b=s.get("blockers") or {}
    lines=[
        f"🔥 <b>ASTRA MICRO v2 — {int(float(s.get('hours',6)))}h</b>","",
        f"Проверок: <b>{s.get('checks',0)}</b>",
        f"Astra calls: <b>{s.get('model_calls',0)}</b>",
        f"LONG/SHORT: <b>{s.get('model_trade_decisions',0)}</b> | WAIT: <b>{s.get('model_waits',0)}</b>",
        f"Открыто: <b>{s.get('opened_trades',0)}</b> | FOK no-fill: <b>{s.get('fok_not_filled',0)}</b>",
        f"Закрыто: <b>{s.get('closed_trades',0)}</b> | Win rate: <b>{s.get('win_rate_pct',0):.1f}%</b>",
        f"Realized NET PnL: <b>${s.get('realized_net_pnl_usd',0):.4f}</b> | Fees: <b>${s.get('realized_fee_usd',0):.4f}</b>",
        f"NET-edge rejects: <b>{s.get('net_edge_rejections',0)}</b>",
        f"Avg spread: <b>{s.get('avg_spread_pct')}</b>% | Avg cost: <b>{s.get('avg_cost_r')}</b>R","",
        "<b>Чаще блокирует:</b>",
    ]
    for k,v in list(b.items())[:8]: lines.append(f"• {k}: <b>{v}</b>")
    if not b: lines.append("• пока данных недостаточно")
    return "\n".join(lines)

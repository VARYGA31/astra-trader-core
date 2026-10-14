#!/usr/bin/env python3
"""
Passive observability / analytics layer.

IMPORTANT:
- Does not change trade signals, thresholds, sizing, leverage or execution.
- Does not call OpenAI.
- Does not place or close orders.
- Persists decision funnel + blocked setup journal under STATE_DIR.
"""
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import config

DIR = Path(config.STATE_DIR)
STATE = DIR / "observability_state.json"
DECISIONS = DIR / "decision_events.jsonl"
SHADOW = DIR / "shadow_setups.jsonl"
NEWS = DIR / "news_events.jsonl"
TRADE_JOURNAL = DIR / "trade_journal.jsonl"

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def _parse_ts(x):
    try:
        return datetime.fromisoformat((x or "").replace("Z","+00:00"))
    except Exception:
        return None

def _default_state():
    return {
        "version": 1,
        "started_at_utc": now_iso(),
        "decision_total": 0,
        "model_calls": 0,
        "model_skips": 0,
        "model_waits": 0,
        "model_wait_categories": {},
        "model_wait_hard_blockers": {},
        "opened_trades": 0,
        "skip_reasons": {},
        "execution_statuses": {},
        "trade_rejection_reasons": {},
        "by_asset": {},
        "last_decision": None,
        "last_model_decision": None,
        "last_trade_rejection": None,
        "last_approved_trade": None,
        "last_shadow_setup": None,
        "last_news_event": None,
    }

def _atomic_save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

def load_state():
    try:
        x = json.loads(STATE.read_text(encoding="utf-8"))
        if not isinstance(x, dict):
            raise ValueError("bad state")
        d = _default_state()
        d.update(x)
        return d
    except Exception:
        return _default_state()

def _save_state(s):
    _atomic_save(STATE, s)

def _inc(d, key, amount=1):
    d[key] = int(d.get(key, 0)) + amount

def _asset_state(s, asset):
    by = s.setdefault("by_asset", {})
    return by.setdefault(asset, {
        "decisions": 0,
        "model_calls": 0,
        "model_skips": 0,
        "model_waits": 0,
        "model_wait_categories": {},
        "opened_trades": 0,
        "skip_reasons": {},
        "trade_rejection_reasons": {},
    })

def _append_jsonl(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, separators=(",",":")) + "\n")
    _maybe_compact(path)

def _maybe_compact(path):
    """Keep passive logs bounded. Never raise into the trading loop."""
    try:
        max_mb = float(config.OBSERVABILITY_LOG_MAX_MB)
        if max_mb <= 0 or not path.exists():
            return
        if path.stat().st_size <= max_mb * 1024 * 1024:
            return
        # Keep roughly the newest half of the configured cap.
        target = int(max_mb * 1024 * 1024 * 0.50)
        with path.open("rb") as f:
            f.seek(max(0, path.stat().st_size - target))
            chunk = f.read()
        # Drop a possibly partial first line.
        first_nl = chunk.find(b"\n")
        if first_nl >= 0:
            chunk = chunk[first_nl+1:]
        tmp = path.with_suffix(path.suffix + ".compact.tmp")
        tmp.write_bytes(chunk)
        tmp.replace(path)
    except Exception:
        return

def _execution_reason(execution):
    if not isinstance(execution, dict):
        return None
    if execution.get("reason"):
        return str(execution.get("reason"))
    risk = execution.get("risk")
    if isinstance(risk, dict) and risk.get("reason"):
        return str(risk.get("reason"))
    return None

def _compact_candidates(mtf):
    out=[]
    for c in (mtf or {}).get("candidates",[]) or []:
        trig15=c.get("trigger_15m") or {}
        trig5=c.get("trigger_5m") or {}
        out.append({
            "direction":c.get("direction"),"passed":bool(c.get("passed")),"mode":c.get("mode"),"quality":c.get("quality"),
            "regime_4h_ok":c.get("regime_4h_ok"),"setup_1h_ok":c.get("setup_1h_ok"),
            "trigger_15m_confirmed":trig15.get("confirmed"),"trigger_15m_count":trig15.get("count"),
            "regime_1h_ok":c.get("regime_1h_ok"),"setup_15m_ok":c.get("setup_15m_ok"),
            "trigger_5m_confirmed":trig5.get("confirmed"),"trigger_5m_count":trig5.get("count"),
        })
    return out

def _best_candidate(mtf):
    candidates = _compact_candidates(mtf)
    if not candidates:
        return None
    def key(x):
        try:
            return float(x.get("quality") or 0)
        except Exception:
            return 0.0
    return max(candidates, key=key)

def _compact_market(package):
    m = (package or {}).get("decision_context", {}).get("market", {})
    spot = m.get("spot", {})
    mtf = m.get("multi_timeframe", {})
    return {
        "price": spot.get("price"),
        "data_quality": m.get("data_quality"),
        "mtf_status": mtf.get("status"),
    }

def record_news_event(event):
    if not config.OBSERVABILITY_ENABLED:
        return {"status":"DISABLED"}
    try:
        row = {
            "timestamp_utc": now_iso(),
            "asset": event.get("asset"),
            "id": event.get("id"),
            "source": event.get("source"),
            "verification_status": event.get("verification_status"),
            "published_at_utc": event.get("published_at_utc"),
            "title": event.get("title"),
            "event_type": event.get("event_type"),
            "impact_hint": event.get("impact_hint"),
            "trade_usable": event.get("trade_usable"),
        }
        _append_jsonl(NEWS, row)
        s = load_state()
        s["last_news_event"] = row
        _save_state(s)
        return {"status":"OK"}
    except Exception as e:
        return {"status":"ERROR","error":str(e)}

def record_decision(package, gate, decision, execution, model_called=False):
    if not config.OBSERVABILITY_ENABLED:
        return {"status":"DISABLED"}

    try:
        asset = str((package or {}).get("asset") or (decision or {}).get("asset") or "").upper()
        gate = gate or {}
        decision = decision or {}
        execution = execution or {}

        mtf = gate.get("mtf") or {}
        best = _best_candidate(mtf)
        gate_reason = gate.get("reason")
        action = str(decision.get("action") or "WAIT").upper()
        exec_status = str(execution.get("status") or "UNKNOWN")
        exec_reason = _execution_reason(execution)

        row = {
            "timestamp_utc": now_iso(),
            "asset": asset,
            "strategy_mode":str((package or {}).get("strategy_mode") or (decision or {}).get("strategy_mode") or "NORMAL").upper(),
            "model_called": bool(model_called),
            "gate_reason": gate_reason,
            "allowed_direction": gate.get("allowed_direction") or mtf.get("direction"),
            "mtf_quality": gate.get("mtf_quality", mtf.get("quality")),
            "mtf_mode": gate.get("mtf_mode", mtf.get("mode")),
            "mtf_minimum_quality": mtf.get("minimum_quality"),
            "mtf_passed": mtf.get("passed"),
            "best_candidate": best,
            "market": _compact_market(package),
            "model_decision": {
                "action": action,
                "confidence": decision.get("confidence"),
                "setup_type": decision.get("setup_type"),
                "reason": decision.get("reason"),
                "wait_category": decision.get("wait_category"),
                "wait_is_hard_blocker": decision.get("wait_is_hard_blocker"),
                "decision_policy_version": decision.get("decision_policy_version"),
                "entry": decision.get("entry"),
                "stop_loss": decision.get("stop_loss"),
                "take_profit_1": decision.get("take_profit_1"),
                "take_profit_2": decision.get("take_profit_2"),
            } if model_called else None,
            "execution": {
                "status": exec_status,
                "reason": exec_reason,
                "stage": execution.get("stage"),
            },
        }
        _append_jsonl(DECISIONS, row)

        s = load_state()
        s["decision_total"] = int(s.get("decision_total",0)) + 1
        a = _asset_state(s, asset)
        a["decisions"] = int(a.get("decisions",0)) + 1

        if model_called:
            s["model_calls"] = int(s.get("model_calls",0)) + 1
            a["model_calls"] = int(a.get("model_calls",0)) + 1
            s["last_model_decision"] = row
            if action == "WAIT":
                s["model_waits"] = int(s.get("model_waits",0)) + 1
                a["model_waits"] = int(a.get("model_waits",0)) + 1
                wait_category=str(decision.get("wait_category") or "UNSPECIFIED")
                _inc(s.setdefault("model_wait_categories",{}),wait_category)
                _inc(a.setdefault("model_wait_categories",{}),wait_category)
                hard_key="HARD" if bool(decision.get("wait_is_hard_blocker")) else "SOFT_OR_UNSPECIFIED"
                _inc(s.setdefault("model_wait_hard_blockers",{}),hard_key)
        else:
            s["model_skips"] = int(s.get("model_skips",0)) + 1
            a["model_skips"] = int(a.get("model_skips",0)) + 1
            reason = str(gate_reason or "UNKNOWN_SKIP")
            _inc(s.setdefault("skip_reasons",{}), reason)
            _inc(a.setdefault("skip_reasons",{}), reason)

        _inc(s.setdefault("execution_statuses",{}), exec_status)

        opened = exec_status in {
            "OKX_DEMO_OPENED","PAPER_OPENED","PAPER_POSITION_OPENED","OPENED"
        }
        if opened:
            s["opened_trades"] = int(s.get("opened_trades",0)) + 1
            a["opened_trades"] = int(a.get("opened_trades",0)) + 1
            trade = execution.get("trade") or {}
            s["last_approved_trade"] = {
                "timestamp_utc": row["timestamp_utc"],
                "asset": asset,
                "strategy_mode":row.get("strategy_mode"),
                "action": action,
                "confidence": decision.get("confidence"),
                "setup_type": decision.get("setup_type"),
                "mtf_quality": row.get("mtf_quality"),
                "execution_status": exec_status,
                "entry": trade.get("entry", decision.get("entry")),
                "planned_entry": trade.get("planned_entry", decision.get("planned_entry")),
                "pre_order_reference": trade.get("pre_order_reference"),
                "entry_order_type": trade.get("entry_order_type"),
                "entry_limit_price": trade.get("entry_limit_price"),
                "fill_slippage_pct": trade.get("fill_slippage_pct"),
                "planned_tp1_r": trade.get("planned_tp1_r"),
                "planned_tp2_r": trade.get("planned_tp2_r"),
                "actual_tp1_r": trade.get("tp1_r"),
                "actual_tp2_r": trade.get("tp2_r"),
                "leverage": trade.get("leverage"),
                "notional_usd": trade.get("notional_usd"),
            }

        # "Trade rejection" means a model produced a non-WAIT trade idea but
        # deterministic execution/risk refused it. Gate skips are tracked separately.
        if model_called and action in {"LONG","SHORT"} and not opened:
            reason = str(exec_reason or exec_status or "UNKNOWN_REJECTION")
            _inc(s.setdefault("trade_rejection_reasons",{}), reason)
            _inc(a.setdefault("trade_rejection_reasons",{}), reason)
            s["last_trade_rejection"] = row

        s["last_decision"] = row

        # Shadow journal: record promising but blocked / rejected setups.
        shadow_written = False
        if config.SHADOW_JOURNAL_ENABLED and best:
            try:
                q = float(best.get("quality") or 0)
            except Exception:
                q = 0.0

            blocked = not bool(mtf.get("passed")) or not bool(model_called) or (
                model_called and exec_status not in {"OKX_DEMO_OPENED","PAPER_OPENED","PAPER_POSITION_OPENED","OPENED"}
            )
            if blocked and q >= float(config.SHADOW_MIN_QUALITY):
                shadow = {
                    "timestamp_utc": row["timestamp_utc"],
                    "asset": asset,
                    "strategy_mode":row.get("strategy_mode"),
                    "price": row["market"].get("price"),
                    "direction": best.get("direction"),
                    "quality": best.get("quality"),
                    "mtf_mode": row.get("mtf_mode") or best.get("mode"),
                    "minimum_quality": row.get("mtf_minimum_quality"),
                    "regime_4h_ok": best.get("regime_4h_ok"),
                    "setup_1h_ok": best.get("setup_1h_ok"),
                    "trigger_15m_confirmed": best.get("trigger_15m_confirmed"),
                    "trigger_15m_count": best.get("trigger_15m_count"),
                    "regime_1h_ok": best.get("regime_1h_ok"),
                    "setup_15m_ok": best.get("setup_15m_ok"),
                    "trigger_5m_confirmed": best.get("trigger_5m_confirmed"),
                    "trigger_5m_count": best.get("trigger_5m_count"),
                    "blocked_reason": gate_reason if not model_called else (exec_reason or decision.get("reason") or exec_status),
                    "model_called": bool(model_called),
                    "model_action": action if model_called else None,
                    "model_confidence": decision.get("confidence") if model_called else None,
                    "model_wait_category": decision.get("wait_category") if model_called and action=="WAIT" else None,
                    "model_wait_is_hard_blocker": decision.get("wait_is_hard_blocker") if model_called and action=="WAIT" else None,
                    "model_wait_reason": decision.get("reason") if model_called and action=="WAIT" else None,
                    "decision_policy_version": decision.get("decision_policy_version") if model_called else None,
                }
                _append_jsonl(SHADOW, shadow)
                s["last_shadow_setup"] = shadow
                shadow_written = True

        _save_state(s)
        return {"status":"OK","shadow_written":shadow_written}
    except Exception as e:
        # Passive observability must never interrupt trading.
        return {"status":"ERROR","error":str(e)}

def _load_jsonl(path):
    out=[]
    try:
        with path.open("r",encoding="utf-8") as f:
            for line in f:
                try:
                    x=json.loads(line)
                    if isinstance(x,dict):
                        out.append(x)
                except Exception:
                    continue
    except Exception:
        pass
    return out

def _dedupe_closes(events):
    out=[]
    seen=set()
    for e in events:
        if e.get("event")!="OKX_POSITION_CLOSED":
            continue
        key = (
            e.get("close_event_id")
            or f"{e.get('asset')}|{e.get('order_id')}|{e.get('opened_at_utc')}|{e.get('exit_price')}|{e.get('reason')}"
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out

def _risk_usd(e):
    try:
        entry=float(e.get("entry"))
        stop=float(e.get("stop_loss"))
        notional=float(e.get("notional_usd"))
        if entry<=0:
            return None
        return notional * abs(entry-stop)/entry
    except Exception:
        return None

def _metrics(events):
    rows=[]
    for e in events:
        try:
            pnl=float(e.get("pnl_usd") or 0)
        except Exception:
            pnl=0.0
        rsk=_risk_usd(e)
        rows.append({
            "pnl":pnl,
            "r": (pnl/rsk) if rsk and rsk>0 else None,
            "timestamp":e.get("timestamp_utc"),
        })

    pnls=[x["pnl"] for x in rows]
    wins=[x for x in pnls if x>0]
    losses=[x for x in pnls if x<0]
    rs=[x["r"] for x in rows if isinstance(x.get("r"),(int,float))]

    streak=0
    max_streak=0
    for x in rows:
        if x["pnl"]<0:
            streak+=1
            max_streak=max(max_streak,streak)
        else:
            streak=0

    gp=sum(wins)
    gl=abs(sum(losses))
    return {
        "trades":len(rows),
        "wins":len(wins),
        "losses":len(losses),
        "win_rate_pct":round((len(wins)/len(rows)*100),2) if rows else 0.0,
        "net_pnl_usd":round(sum(pnls),6),
        "avg_pnl_usd":round(statistics.mean(pnls),6) if pnls else 0.0,
        "profit_factor":round(gp/gl,4) if gl>0 else (None if gp==0 else "INF"),
        "avg_r":round(statistics.mean(rs),4) if rs else None,
        "max_losing_streak":max_streak,
    }

def _group_metrics(events, key_fn):
    d=defaultdict(list)
    for e in events:
        d[str(key_fn(e) or "UNKNOWN")].append(e)
    return {k:_metrics(v) for k,v in sorted(d.items())}

def trade_performance(since_utc=None):
    closes=_dedupe_closes(_load_jsonl(TRADE_JOURNAL))
    if since_utc:
        cutoff=_parse_ts(since_utc)
        if cutoff:
            closes=[
                e for e in closes
                if (_parse_ts(e.get("timestamp_utc")) and _parse_ts(e.get("timestamp_utc"))>=cutoff)
            ]

    return {
        "since_utc": since_utc,
        "overall": _metrics(closes),
        "by_asset": _group_metrics(closes, lambda e:e.get("asset")),
        "by_direction": _group_metrics(closes, lambda e:e.get("side")),
        "by_setup_type": _group_metrics(closes, lambda e:e.get("setup_type")),
        "by_strategy_mode": _group_metrics(closes, lambda e:e.get("strategy_mode") or "NORMAL"),
    }

def _decision_funnel(since_utc=None):
    rows=_load_jsonl(DECISIONS)
    cutoff=_parse_ts(since_utc) if since_utc else None
    if cutoff:
        rows=[x for x in rows if (_parse_ts(x.get("timestamp_utc")) and _parse_ts(x.get("timestamp_utc"))>=cutoff)]

    skips=defaultdict(int)
    rejects=defaultdict(int)
    by_asset=defaultdict(lambda:{
        "decisions":0,"model_calls":0,"model_skips":0,"model_waits":0,"opened":0
    })
    by_mode=defaultdict(lambda:{"decisions":0,"model_calls":0,"model_skips":0,"model_waits":0,"opened":0})
    model_calls=0
    model_skips=0
    model_waits=0
    wait_categories=defaultdict(int)
    wait_hardness=defaultdict(int)
    opened=0

    for x in rows:
        asset=x.get("asset","UNKNOWN")
        mode=str(x.get("strategy_mode") or "NORMAL").upper()
        a=by_asset[asset]; m=by_mode[mode]
        a["decisions"]+=1; m["decisions"]+=1
        if x.get("model_called"):
            model_calls+=1;a["model_calls"]+=1;m["model_calls"]+=1
            md=x.get("model_decision") or {}
            if str(md.get("action","")).upper()=="WAIT":
                model_waits+=1;a["model_waits"]+=1;m["model_waits"]+=1
                cat=str(md.get("wait_category") or "UNCLASSIFIED_LEGACY")
                wait_categories[cat]+=1
                wait_hardness["HARD" if bool(md.get("wait_is_hard_blocker")) else "SOFT_OR_UNSPECIFIED"]+=1
        else:
            model_skips+=1;a["model_skips"]+=1;m["model_skips"]+=1
            skips[str(x.get("gate_reason") or "UNKNOWN_SKIP")]+=1

        ex=x.get("execution") or {}
        status=ex.get("status")
        if status in {"OKX_DEMO_OPENED","PAPER_OPENED","PAPER_POSITION_OPENED","OPENED"}:
            opened+=1;a["opened"]+=1;m["opened"]+=1
        elif x.get("model_called") and str((x.get("model_decision") or {}).get("action","")).upper() in {"LONG","SHORT"}:
            rejects[str(ex.get("reason") or status or "UNKNOWN_REJECTION")]+=1

    return {
        "since_utc":since_utc,
        "decisions":len(rows),
        "model_calls":model_calls,
        "model_skips":model_skips,
        "model_waits":model_waits,
        "model_wait_categories":dict(sorted(wait_categories.items(),key=lambda kv:(-kv[1],kv[0]))),
        "model_wait_hardness":dict(sorted(wait_hardness.items(),key=lambda kv:(-kv[1],kv[0]))),
        "opened_trades":opened,
        "skip_reasons":dict(sorted(skips.items(),key=lambda kv:(-kv[1],kv[0]))),
        "trade_rejection_reasons":dict(sorted(rejects.items(),key=lambda kv:(-kv[1],kv[0]))),
        "by_asset":dict(by_asset),
        "by_strategy_mode":dict(by_mode),
    }

def recent_shadow(limit=None):
    limit=int(limit or config.ANALYTICS_RECENT_LIMIT)
    rows=_load_jsonl(SHADOW)
    return rows[-limit:]

def health_summary():
    s=load_state()
    return {
        "started_at_utc":s.get("started_at_utc"),
        "decision_total":s.get("decision_total",0),
        "model_calls":s.get("model_calls",0),
        "model_skips":s.get("model_skips",0),
        "model_waits":s.get("model_waits",0),
        "model_wait_categories":s.get("model_wait_categories",{}),
        "model_wait_hard_blockers":s.get("model_wait_hard_blockers",{}),
        "opened_trades":s.get("opened_trades",0),
        "skip_reasons":s.get("skip_reasons",{}),
        "trade_rejection_reasons":s.get("trade_rejection_reasons",{}),
        "by_asset":s.get("by_asset",{}),
        "last_model_decision":s.get("last_model_decision"),
        "last_trade_rejection":s.get("last_trade_rejection"),
        "last_approved_trade":s.get("last_approved_trade"),
        "last_shadow_setup":s.get("last_shadow_setup"),
        "last_news_event":s.get("last_news_event"),
    }

def analytics_report(days=None):
    s=load_state()
    since=s.get("started_at_utc")
    requested_since=None
    if days is not None:
        try:
            requested_since=(datetime.now(timezone.utc)-timedelta(days=float(days))).isoformat()
        except Exception:
            requested_since=None

    return {
        "generated_at_utc":now_iso(),
        "observability_started_at_utc":since,
        "decision_funnel_since_install":_decision_funnel(since),
        "decision_funnel_requested_window":_decision_funnel(requested_since) if requested_since else None,
        "trades_since_install":trade_performance(since),
        "trades_all_journal_history":trade_performance(None),
        "recent_shadow_setups":recent_shadow(),
    }

if __name__=="__main__":
    print(json.dumps(analytics_report(),ensure_ascii=False,indent=2))

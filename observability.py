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
import adaptive_memory
import fok_shadow_analyzer

DIR = Path(config.STATE_DIR)
STATE = DIR / "observability_state.json"
DECISIONS = DIR / "decision_events.jsonl"
SHADOW = DIR / "shadow_setups.jsonl"
SHADOW_OUTCOMES = DIR / "mtf_shadow_outcomes.jsonl"
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
        trig1=c.get("trigger_1m") or {}
        out.append({
            "direction":c.get("direction"),"passed":bool(c.get("passed")),"mode":c.get("mode"),"quality":c.get("quality"),
            "regime_4h_ok":c.get("regime_4h_ok"),"setup_1h_ok":c.get("setup_1h_ok"),
            "trigger_15m_confirmed":trig15.get("confirmed"),"trigger_15m_count":trig15.get("count"),
            "trigger_15m_components":trig15.get("components") or {},
            "normal_blockers":c.get("normal_blockers") or [],
            "transition_blockers":c.get("transition_blockers") or [],
            "failed_checks":c.get("failed_checks") or [],
            "primary_blocker":c.get("primary_blocker"),
            "regime_1h_ok":c.get("regime_1h_ok"),"setup_15m_ok":c.get("setup_15m_ok"),
            "trigger_5m_confirmed":trig5.get("confirmed"),"trigger_5m_count":trig5.get("count"),
            "micro_context_5m_ok":c.get("context_5m_ok"),"micro_setup_3m_ok":c.get("setup_3m_ok"),
            "trigger_1m_confirmed":trig1.get("confirmed"),"trigger_1m_count":trig1.get("count"),
            "micro_score_5m":c.get("score_5m"),"micro_score_3m":c.get("score_3m"),
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
        "generated_at_utc":m.get("generated_at_utc"),
        "price": spot.get("price"),
        "perp_okx_last_price":(m.get("perp_okx") or {}).get("last_price"),
        "microstructure_source":spot.get("microstructure_source"),
        "microstructure_spread_pct":spot.get("microstructure_spread_pct"),
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
        _evaluate_mtf_shadow_outcomes(package, asset)
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
            "mtf_blockers":mtf.get("blockers") or [],
            "mtf_transition_blockers":mtf.get("transition_blockers") or [],
            "mtf_primary_blocker":mtf.get("primary_blocker"),
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
                "model_entry_raw":decision.get("model_entry_raw"),
                "entry_reference_source":decision.get("entry_reference_source"),
                "entry_snapshot_at_utc":decision.get("_entry_snapshot_at_utc"),
                "model_started_at_utc":decision.get("_model_started_at_utc"),
                "model_finished_at_utc":decision.get("_model_finished_at_utc"),
                "model_latency_ms":decision.get("_model_latency_ms"),
                "stop_loss": decision.get("stop_loss"),
                "take_profit_1": decision.get("take_profit_1"),
                "take_profit_2": decision.get("take_profit_2"),
            } if model_called else None,
            "shadow_council": (package or {}).get("shadow_council"),
            "execution": {
                "status": exec_status,
                "reason": exec_reason,
                "stage": execution.get("stage"),
                "error_type":execution.get("error_type"),
                "error":str(execution.get("error") or "")[:500] or None,
                "drift_pct":execution.get("drift_pct"),
                "maximum_pct":execution.get("maximum_pct"),
                "planned_entry":execution.get("planned_entry"),
                "current_price":execution.get("current_price"),
                "price_source":execution.get("price_source"),
                "snapshot_swap_price":execution.get("snapshot_swap_price"),
                "snapshot_at_utc":execution.get("snapshot_at_utc"),
                "planned_entry_raw":execution.get("planned_entry_raw"),
                "model_started_at_utc":execution.get("model_started_at_utc"),
                "model_finished_at_utc":execution.get("model_finished_at_utc"),
                "model_latency_ms":execution.get("model_latency_ms"),
                "ticker_started_at_utc":execution.get("ticker_started_at_utc"),
                "ticker_finished_at_utc":execution.get("ticker_finished_at_utc"),
                "ticker_latency_ms":execution.get("ticker_latency_ms"),
                "tradability_reason":((execution.get("tradability") or {}).get("reason")),
                "tradability_instrument":((execution.get("tradability") or {}).get("instrument")),
                "current_exposure_usd":execution.get("current_exposure_usd"),
                "proposed_notional_usd":execution.get("proposed_notional_usd"),
                "exposure_cap_usd":execution.get("exposure_cap_usd"),
                "pre_order_reference":execution.get("pre_order_reference"),
                "entry_limit_price":execution.get("entry_limit_price"),
                "order_state":execution.get("order_state"),
                "entry_attempt_count":len(execution.get("entry_attempts") or []),
                "micro_net_edge":(
                    (execution.get("micro_net_edge") or {})
                    or ((execution.get("execution_quality") or {}).get("micro_net_edge") or {})
                ),
            },
        }
        _append_jsonl(DECISIONS, row)
        # Passive FOK evidence capture. Any failure here is diagnostic-only and
        # must never affect live order/risk behavior.
        try:
            fok_shadow_analyzer.record_rejection(package,decision,execution)
        except Exception:
            pass

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
                "micro_net_edge":trade.get("micro_net_edge"),
                "micro_fee_info":trade.get("micro_fee_info"),
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
                    "mtf_replay_version":1,
                    "setup_id":_shadow_setup_id({
                        "timestamp_utc":row["timestamp_utc"],
                        "asset":asset,
                        "direction":best.get("direction"),
                        "trigger_candle_id":mtf.get("trigger_candle_id"),
                    }),
                    "asset": asset,
                    "strategy_mode":row.get("strategy_mode"),
                    "price": row["market"].get("price"),
                    "direction": best.get("direction"),
                    "quality": best.get("quality"),
                    "mtf_mode": row.get("mtf_mode") or best.get("mode"),
                    "trigger_candle_id":mtf.get("trigger_candle_id"),
                    "mtf_blockers":mtf.get("blockers") or best.get("normal_blockers") or [],
                    "mtf_transition_blockers":mtf.get("transition_blockers") or best.get("transition_blockers") or [],
                    "mtf_primary_blocker":mtf.get("primary_blocker") or best.get("primary_blocker"),
                    "minimum_quality": row.get("mtf_minimum_quality"),
                    "regime_4h_ok": best.get("regime_4h_ok"),
                    "setup_1h_ok": best.get("setup_1h_ok"),
                    "trigger_15m_confirmed": best.get("trigger_15m_confirmed"),
                    "trigger_15m_count": best.get("trigger_15m_count"),
                    "regime_1h_ok": best.get("regime_1h_ok"),
                    "setup_15m_ok": best.get("setup_15m_ok"),
                    "trigger_5m_confirmed": best.get("trigger_5m_confirmed"),
                    "trigger_5m_count": best.get("trigger_5m_count"),
                    "micro_context_5m_ok":best.get("micro_context_5m_ok"),
                    "micro_setup_3m_ok":best.get("micro_setup_3m_ok"),
                    "trigger_1m_confirmed":best.get("trigger_1m_confirmed"),
                    "trigger_1m_count":best.get("trigger_1m_count"),
                    "microstructure_source":row.get("market",{}).get("microstructure_source"),
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

def _shadow_setup_id(row):
    ts=str((row or {}).get("timestamp_utc") or "")
    asset=str((row or {}).get("asset") or "").upper()
    direction=str((row or {}).get("direction") or "").upper()
    candle=str((row or {}).get("trigger_candle_id") or "")
    return "|".join((ts,asset,direction,candle))

def _market_reference_price(package):
    market=(package or {}).get("decision_context",{}).get("market",{})
    for value in (
        (market.get("perp_okx") or {}).get("last_price"),
        (market.get("spot") or {}).get("price"),
    ):
        try:
            value=float(value)
            if value>0:
                return value
        except Exception:
            continue
    return None

def _evaluate_mtf_shadow_outcomes(package, asset):
    """Evaluate blocked MTF setups using later snapshots only; never trades."""
    if not getattr(config,"MTF_SHADOW_REPLAY_ENABLED",True):
        return {"status":"DISABLED","evaluated":0}
    try:
        current_price=_market_reference_price(package)
        if not current_price or not asset:
            return {"status":"NO_PRICE","evaluated":0}
        market=(package or {}).get("decision_context",{}).get("market",{})
        current_ts=_parse_ts(market.get("generated_at_utc")) or datetime.now(timezone.utc)
        setups=_load_jsonl(SHADOW)
        outcomes=_load_jsonl(SHADOW_OUTCOMES)
        done={
            (str(x.get("setup_id") or ""),int(x.get("horizon_minutes") or 0))
            for x in outcomes
        }
        horizons=tuple(sorted(set(
            int(x) for x in getattr(config,"MTF_SHADOW_REPLAY_HORIZONS_MINUTES",(60,240))
            if int(x)>0
        )))
        batch=max(1,int(getattr(config,"MTF_SHADOW_REPLAY_EVAL_BATCH",200)))
        evaluated=0
        for setup in reversed(setups):
            if evaluated>=batch:
                break
            if str(setup.get("asset") or "").upper()!=str(asset).upper():
                continue
            if str(setup.get("blocked_reason") or "")!="MTF_NOT_ALIGNED":
                continue
            if int(setup.get("mtf_replay_version") or 0)!=1:
                continue
            setup_ts=_parse_ts(setup.get("timestamp_utc"))
            if not setup_ts:
                continue
            try:
                entry=float(setup.get("price"))
            except Exception:
                continue
            if entry<=0:
                continue
            direction=str(setup.get("direction") or "").upper()
            if direction not in {"LONG","SHORT"}:
                continue
            setup_id=str(setup.get("setup_id") or _shadow_setup_id(setup))
            age_minutes=(current_ts-setup_ts).total_seconds()/60.0
            max_delay=max(0,int(getattr(config,"MTF_SHADOW_REPLAY_MAX_DELAY_MINUTES",90)))
            for horizon in horizons:
                key=(setup_id,int(horizon))
                if key in done or age_minutes<float(horizon):
                    continue
                if age_minutes>float(horizon)+float(max_delay):
                    continue
                raw_return_pct=(float(current_price)-entry)/entry*100.0
                signed_return_pct=raw_return_pct if direction=="LONG" else -raw_return_pct
                outcome={
                    "mtf_replay_version":1,
                    "evaluated_at_utc":current_ts.isoformat(),
                    "setup_timestamp_utc":setup.get("timestamp_utc"),
                    "setup_id":setup_id,
                    "asset":asset,
                    "direction":direction,
                    "entry_price":entry,
                    "evaluation_price":float(current_price),
                    "horizon_minutes":int(horizon),
                    "evaluation_age_minutes":round(age_minutes,2),
                    "evaluation_delay_minutes":round(max(0.0,age_minutes-float(horizon)),2),
                    "raw_return_pct":round(raw_return_pct,6),
                    "signed_return_pct":round(signed_return_pct,6),
                    "positive":bool(signed_return_pct>0),
                    "quality":setup.get("quality"),
                    "mtf_primary_blocker":setup.get("mtf_primary_blocker"),
                    "mtf_blockers":setup.get("mtf_blockers") or [],
                    "mtf_transition_blockers":setup.get("mtf_transition_blockers") or [],
                }
                _append_jsonl(SHADOW_OUTCOMES,outcome)
                done.add(key)
                evaluated+=1
                if evaluated>=batch:
                    break
        return {"status":"OK","evaluated":evaluated}
    except Exception as e:
        return {"status":"ERROR","evaluated":0,"error":str(e)[:300]}

def _shadow_metrics(rows):
    vals=[]
    for x in rows:
        try:
            vals.append(float(x.get("signed_return_pct")))
        except Exception:
            continue
    positives=[v for v in vals if v>0]
    return {
        "samples":len(vals),
        "positive":len(positives),
        "hit_rate_pct":round(len(positives)/len(vals)*100.0,2) if vals else 0.0,
        "avg_signed_return_pct":round(statistics.mean(vals),6) if vals else None,
        "median_signed_return_pct":round(statistics.median(vals),6) if vals else None,
    }

def shadow_replay_summary(hours=168):
    rows=[
        x for x in _load_jsonl(SHADOW_OUTCOMES)
        if int(x.get("mtf_replay_version") or 0)==1
    ]
    try:
        cutoff=datetime.now(timezone.utc)-timedelta(hours=float(hours))
        rows=[
            x for x in rows
            if (_parse_ts(x.get("setup_timestamp_utc")) and _parse_ts(x.get("setup_timestamp_utc"))>=cutoff)
        ]
    except Exception:
        pass
    by_horizon=defaultdict(list)
    by_blocker=defaultdict(list)
    for x in rows:
        by_horizon[str(int(x.get("horizon_minutes") or 0))].append(x)
        blocker=str(x.get("mtf_primary_blocker") or "UNCLASSIFIED")
        by_blocker[blocker].append(x)
    return {
        "status":"OK" if getattr(config,"MTF_SHADOW_REPLAY_ENABLED",True) else "DISABLED",
        "window_hours":hours,
        "evaluated":len(rows),
        "by_horizon":{k:_shadow_metrics(v) for k,v in sorted(by_horizon.items(),key=lambda kv:int(kv[0]))},
        "by_primary_blocker":{
            k:_shadow_metrics(v)
            for k,v in sorted(by_blocker.items(),key=lambda kv:(-len(kv[1]),kv[0]))
        },
        "recent":rows[-10:],
    }

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
    mtf_blockers=defaultdict(int)
    by_asset=defaultdict(lambda:{
        "decisions":0,"model_calls":0,"model_skips":0,"model_waits":0,"opened":0,
        "skip_reasons":defaultdict(int),
        "mtf_blockers":defaultdict(int),
        "wait_categories":defaultdict(int),
        "trade_rejection_reasons":defaultdict(int),
        "last_rejection":None,
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
                a["wait_categories"][cat]+=1
                wait_hardness["HARD" if bool(md.get("wait_is_hard_blocker")) else "SOFT_OR_UNSPECIFIED"]+=1
        else:
            model_skips+=1;a["model_skips"]+=1;m["model_skips"]+=1
            skip_reason=str(x.get("gate_reason") or "UNKNOWN_SKIP")
            skips[skip_reason]+=1
            a["skip_reasons"][skip_reason]+=1
            if skip_reason=="MTF_NOT_ALIGNED":
                for blocker in (x.get("mtf_blockers") or []):
                    blocker=str(blocker)
                    mtf_blockers[blocker]+=1
                    a["mtf_blockers"][blocker]+=1

        ex=x.get("execution") or {}
        status=ex.get("status")
        if status in {"OKX_DEMO_OPENED","PAPER_OPENED","PAPER_POSITION_OPENED","OPENED"}:
            opened+=1;a["opened"]+=1;m["opened"]+=1
        elif x.get("model_called") and str((x.get("model_decision") or {}).get("action","")).upper() in {"LONG","SHORT"}:
            reject_reason=str(ex.get("reason") or status or "UNKNOWN_REJECTION")
            rejects[reject_reason]+=1
            a["trade_rejection_reasons"][reject_reason]+=1
            a["last_rejection"]={
                "timestamp_utc":x.get("timestamp_utc"),
                "reason":reject_reason,
                "stage":ex.get("stage"),
                "error_type":ex.get("error_type"),
                "error":ex.get("error"),
                "drift_pct":ex.get("drift_pct"),
                "maximum_pct":ex.get("maximum_pct"),
                "planned_entry":ex.get("planned_entry"),
                "current_price":ex.get("current_price"),
                "price_source":ex.get("price_source"),
                "snapshot_swap_price":ex.get("snapshot_swap_price"),
                "snapshot_at_utc":ex.get("snapshot_at_utc"),
                "planned_entry_raw":ex.get("planned_entry_raw"),
                "model_started_at_utc":ex.get("model_started_at_utc"),
                "model_finished_at_utc":ex.get("model_finished_at_utc"),
                "model_latency_ms":ex.get("model_latency_ms"),
                "ticker_started_at_utc":ex.get("ticker_started_at_utc"),
                "ticker_finished_at_utc":ex.get("ticker_finished_at_utc"),
                "ticker_latency_ms":ex.get("ticker_latency_ms"),
                "tradability_reason":ex.get("tradability_reason"),
                "tradability_instrument":ex.get("tradability_instrument"),
                "current_exposure_usd":ex.get("current_exposure_usd"),
                "proposed_notional_usd":ex.get("proposed_notional_usd"),
                "exposure_cap_usd":ex.get("exposure_cap_usd"),
            }

    asset_out={}
    for asset,a in by_asset.items():
        asset_out[asset]={
            **{k:v for k,v in a.items() if k not in {"skip_reasons","mtf_blockers","wait_categories","trade_rejection_reasons"}},
            "skip_reasons":dict(sorted(a["skip_reasons"].items(),key=lambda kv:(-kv[1],kv[0]))),
            "mtf_blockers":dict(sorted(a["mtf_blockers"].items(),key=lambda kv:(-kv[1],kv[0]))),
            "wait_categories":dict(sorted(a["wait_categories"].items(),key=lambda kv:(-kv[1],kv[0]))),
            "trade_rejection_reasons":dict(sorted(a["trade_rejection_reasons"].items(),key=lambda kv:(-kv[1],kv[0]))),
        }

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
        "mtf_blockers":dict(sorted(mtf_blockers.items(),key=lambda kv:(-kv[1],kv[0]))),
        "trade_rejection_reasons":dict(sorted(rejects.items(),key=lambda kv:(-kv[1],kv[0]))),
        "by_asset":asset_out,
        "by_strategy_mode":dict(by_mode),
    }

def recent_shadow(limit=None):
    limit=int(limit or config.ANALYTICS_RECENT_LIMIT)
    rows=_load_jsonl(SHADOW)
    return rows[-limit:]

def recent_closed(limit=5):
    closes=_dedupe_closes(_load_jsonl(TRADE_JOURNAL))
    out=[]
    for e in closes[-max(1,int(limit)):]:
        out.append({
            "timestamp_utc":e.get("timestamp_utc"),
            "asset":e.get("asset"),
            "side":e.get("side"),
            "pnl_usd":e.get("pnl_usd"),
            "reason":e.get("reason"),
            "setup_type":e.get("setup_type"),
            "strategy_mode":e.get("strategy_mode") or "NORMAL",
            "entry":e.get("entry"),
            "exit_price":e.get("exit_price"),
            "stop_loss":e.get("stop_loss"),
            "notional_usd":e.get("notional_usd"),
            "leverage":e.get("leverage"),
            "confidence":e.get("confidence"),
            "mtf_quality":e.get("mtf_quality"),
            "trade_quality":e.get("trade_quality"),
            "fill_slippage_pct":e.get("fill_slippage_pct"),
            "opened_at_utc":e.get("opened_at_utc"),
        })
    return out

def diagnostic_digest(hours=24,recent_closed_limit=5):
    try:
        since=(datetime.now(timezone.utc)-timedelta(hours=float(hours))).isoformat()
    except Exception:
        since=None
    return {
        "window_hours":hours,
        "since_utc":since,
        "decision_funnel":_decision_funnel(since),
        "trade_performance":trade_performance(since),
        "mtf_shadow_replay":shadow_replay_summary(float(hours)),
        "recent_closed":recent_closed(recent_closed_limit),
    }

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
        "adaptive_brain":adaptive_memory.load_brain(),
        "adaptive_learning_7d":adaptive_memory.summary(168),
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
        "mtf_shadow_replay":shadow_replay_summary(168),
        "adaptive_brain":adaptive_memory.load_brain(),
        "adaptive_learning_7d":adaptive_memory.summary(168),
    }

if __name__=="__main__":
    print(json.dumps(analytics_report(),ensure_ascii=False,indent=2))

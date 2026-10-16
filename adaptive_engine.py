#!/usr/bin/env python3
"""Runtime orchestration for ASTRA ADAPTIVE v1.

One cycle:
1) build fresh packages for all adaptive assets,
2) call one multi-asset model,
3) persist every opinion for outcome learning,
4) execute at most one best opportunity through existing deterministic safety.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import config
import trade_cycle
import adaptive_client
import adaptive_memory
import adaptive_cost
import adaptive_trainer

STATE=Path(config.STATE_DIR)/"adaptive_cycle_state.json"

def _load_state():
    try:
        x=json.loads(STATE.read_text(encoding="utf-8"))
        return x if isinstance(x,dict) else {}
    except Exception:
        return {}

def _save_state(x):
    STATE.parent.mkdir(parents=True,exist_ok=True)
    tmp=STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding="utf-8")
    tmp.replace(STATE)

def _candle_id(package):
    frames=(package or {}).get("decision_context",{}).get("market",{}).get("multi_timeframe",{}).get("frames",{})
    return (frames.get("5m") or {}).get("last_confirmed_close_time_ms")

def _hard_guard_summary(packages):
    out={}
    for asset,p in packages.items():
        g=p.get("guards",{})
        out[asset]={
            "market_stale":bool(g.get("market_stale")),
            "market_ok":bool(g.get("market_ok")),
            "news_ok":bool(g.get("news_ok")),
            "critical_news_verified":bool(g.get("critical_news_verified")),
            "trading_halted":bool(g.get("trading_halted")),
            "cooldown_active":bool((g.get("cooldown") or {}).get("active")),
        }
    return out

def should_run(packages, force=False):
    if force:
        return True, "FORCED"
    current={a:_candle_id(p) for a,p in packages.items()}
    old=_load_state().get("last_5m_candles") or {}
    changed=any(current.get(a) is not None and current.get(a)!=old.get(a) for a in current)
    return changed, "NEW_5M_CANDLE" if changed else "SAME_5M_CANDLE"

def _mark(packages,result=None,model_called=False,plan=None):
    old=_load_state()
    x={
        **old,
        "last_5m_candles":{a:_candle_id(p) for a,p in packages.items()},
        "last_cycle_at_utc":datetime.now(timezone.utc).isoformat(),
        "last_cycle_id":(result or {}).get("cycle_id"),
        "last_cost_plan":plan,
    }
    if model_called:
        x["last_model_call_at_utc"]=datetime.now(timezone.utc).isoformat()
    _save_state(x)

def _decision_from_best(best, package):
    strategy=str(best.get("strategy") or "WAIT").upper()
    action=str(best.get("action") or "WAIT").upper()
    asset=str(best.get("asset") or "").upper()
    quality=float(best.get("setup_quality") or 0)
    confidence=float(best.get("confidence") or 0)
    tier=str(best.get("scalp_tier") or "FAST").upper()
    if tier not in {"PRIME","FAST"}:
        tier="FAST"
    return {
        "asset":asset,
        "action":action,
        "entry":best.get("entry"),
        "stop_loss":best.get("stop_loss"),
        "take_profit_1":best.get("take_profit_1"),
        "take_profit_2":best.get("take_profit_2"),
        "confidence":confidence,
        "data_quality":((package.get("decision_context",{}).get("market",{}).get("data_quality") or {}).get("status") or "FAILED"),
        "volatility_regime":best.get("volatility_regime") or "NORMAL",
        "setup_type":best.get("setup_type") or "ADAPTIVE",
        "reason":best.get("reason") or "",
        "strategy_mode":strategy,
        "timeframe":"5m" if strategy=="SCALP" else config.TRADING_TIMEFRAME,
        "adaptive_mode":True,
        "adaptive_setup_quality":quality,
        "mtf_quality":quality,
        "scalp_tier":tier if strategy=="SCALP" else None,
        "decision_policy_version":"adaptive_trainer_v2",
        "time_horizon_minutes":best.get("time_horizon_minutes"),
        "trainer_candidate_id":best.get("candidate_id"),
        "trainer_learning":best.get("trainer_learning"),
    }

def run_once(force=False):
    assets=tuple(a for a in config.ADAPTIVE_ALLOWED_ASSETS if a in config.ALLOWED_ASSETS)
    packages={a:trade_cycle.prepare(a,config.ADAPTIVE_NEWS_HOURS,"AUTO") for a in assets}

    run,reason=should_run(packages,force=force)
    if not run:
        return {
            "status":"SKIPPED",
            "reason":reason,
            "packages":packages,
            "hard_guards":_hard_guard_summary(packages),
            "cost":adaptive_cost.budget_status(),
        }

    trainer=None
    if config.ADAPTIVE_TRAINER_V2_ENABLED:
        trainer=adaptive_trainer.process(packages)
        ranked=list(trainer.get("ranked") or [])
        threshold=float(
            config.ADAPTIVE_TRAINER_EVENT_MIN_MODEL_QUALITY
            if force else config.ADAPTIVE_TRAINER_MIN_MODEL_QUALITY
        )

        def min_quality(c):
            strategy=str(c.get("strategy") or "").upper()
            if strategy=="NORMAL":
                return max(threshold,float(config.MTF_MIN_QUALITY))
            tier=str(c.get("scalp_tier") or "FAST").upper()
            if tier=="PRIME":
                return max(threshold,float(config.SCALP_MIN_QUALITY))
            return max(threshold,float(config.SCALP_FAST_MIN_QUALITY))

        candidates=[x for x in ranked if float(x.get("quality") or 0)>=min_quality(x)]
        plan={
            "call_model":False,
            "reason":"TRAINER_NO_ACTIONABLE_CANDIDATE",
            "trainer_best":trainer.get("best"),
            "trainer_actionable":len(candidates),
        }

        gap_seconds=adaptive_cost.seconds_since(_load_state().get("last_model_call_at_utc"))
        minimum_gap=float(config.ADAPTIVE_TRAINER_MODEL_MIN_GAP_MINUTES)*60.0
        if candidates and gap_seconds<minimum_gap:
            plan["reason"]="TRAINER_MODEL_COOLDOWN"
            plan["seconds_until_model_allowed"]=max(0,int(minimum_gap-gap_seconds))
            _mark(packages,None,model_called=False,plan=plan)
            learning=adaptive_memory.evaluate_due()
            return {
                "status":"SKIPPED",
                "reason":plan["reason"],
                "packages":packages,
                "hard_guards":_hard_guard_summary(packages),
                "cost_plan":plan,
                "trainer":trainer,
                "learning":learning,
            }

        budget=adaptive_cost.budget_status()
        if candidates and not budget.get("allowed"):
            plan.update({"reason":budget.get("reason"),"budget":budget})
            _mark(packages,None,model_called=False,plan=plan)
            learning=adaptive_memory.evaluate_due()
            return {
                "status":"SKIPPED",
                "reason":plan["reason"],
                "packages":packages,
                "hard_guards":_hard_guard_summary(packages),
                "cost_plan":plan,
                "trainer":trainer,
                "learning":learning,
            }

        if not candidates:
            _mark(packages,None,model_called=False,plan=plan)
            learning=adaptive_memory.evaluate_due()
            return {
                "status":"SKIPPED",
                "reason":plan["reason"],
                "packages":packages,
                "hard_guards":_hard_guard_summary(packages),
                "cost_plan":plan,
                "trainer":trainer,
                "learning":learning,
            }

        selected=candidates[:max(1,int(config.ADAPTIVE_TRAINER_CANDIDATES_TO_MODEL))]
        plan.update({
            "call_model":True,
            "reason":"TRAINER_ACTIONABLE_CANDIDATE",
            "budget":budget,
            "candidate_ids":[x.get("candidate_id") for x in selected],
        })
        result=adaptive_client.decide_market(
            packages,
            trainer_candidates=selected,
            trainer_summary=trainer.get("summary"),
        )
    else:
        if config.ADAPTIVE_COST_SMART_ENABLED:
            plan=adaptive_cost.plan(packages,_load_state(),force=force)
            if not plan.get("call_model"):
                _mark(packages,None,model_called=False,plan=plan)
                learning=adaptive_memory.evaluate_due()
                return {
                    "status":"SKIPPED",
                    "reason":plan.get("reason") or "COST_SMART_WAIT",
                    "packages":packages,
                    "hard_guards":_hard_guard_summary(packages),
                    "cost_plan":plan,
                    "learning":learning,
                }
        else:
            plan={"call_model":True,"reason":"COST_SMART_DISABLED"}

        result=adaptive_client.decide_market(packages)
    adaptive_memory.record_cycle(result,packages)
    _mark(packages,result,model_called=True,plan=plan)

    best=result.get("best_opportunity") or {}
    action=str(best.get("action") or "WAIT").upper()
    asset=str(best.get("asset") or "").upper()
    execution={"status":"NO_TRADE","reason":"ADAPTIVE_WAIT"}

    if action in {"LONG","SHORT"} and asset in packages:
        decision=_decision_from_best(best,packages[asset])
        execution=trade_cycle.execute(decision)
    else:
        decision={
            "asset":asset or "MULTI",
            "action":"WAIT",
            "reason":best.get("reason") or result.get("market_summary") or "No adaptive opportunity",
            "strategy_mode":"AUTO",
            "decision_policy_version":"adaptive_trainer_v2"
        }

    learning=adaptive_memory.evaluate_due()
    return {
        "status":"OK",
        "reason":"ADAPTIVE_TRAINER_CYCLE" if config.ADAPTIVE_TRAINER_V2_ENABLED else "ADAPTIVE_CYCLE",
        "result":result,
        "decision":decision,
        "execution":execution,
        "packages":packages,
        "learning":learning,
        "hard_guards":_hard_guard_summary(packages),
        "cost_plan":plan,
        "cost":adaptive_cost.usage_today(),
        "trainer":trainer,
    }

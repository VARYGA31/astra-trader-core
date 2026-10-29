#!/usr/bin/env python3
import json,time,threading,traceback,hmac
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from datetime import datetime,timezone

import config,news_listener,position_monitor,trade_cycle,paper_execution,execution_router,decision_gate,observability
import strategy_mode,micro_decision_gate,telegram_control,micro_stats,micro_market_stream,micro_second_shadow,crypto_shadow_lab,trade_universe,market_scanner,agent_council
import adaptive_memory,adaptive_cost,adaptive_trainer,multi_market_trainer,strategy_tournament,alpha_factory,mission_control,model_budget
import position_exit_guard
import fok_shadow_analyzer,exit_shadow_tournament
import execution_audit
import trade_incident_review
import mixed4h_research
import telegram_notifier
from astra_client import decide

R={
    "status":"starting",
    "started_at_utc":datetime.now(timezone.utc).isoformat(),
    "last_error":None,
    "worker_exception_circuit":{"active":False,"consecutive":0,"threshold":config.WORKER_EXCEPTION_PAUSE_THRESHOLD},
    "equity_guard":{"verified":None,"status":"NOT_YET_CHECKED"},
    "execution_mode":config.EXECUTION_MODE,
    "decision_engine_enabled":bool(config.AUTO_DECISION),
    "trade_execution_enabled":bool(config.AUTO_PAPER_EXECUTION),
    "last_news":None,
    "last_position_check":None,
    "last_exit_check":None,
    "last_news_exit_reviews":[],
    "last_decisions":{},
    "model_calls":0,
    "model_skips":0,
    "exit_model_calls":0,
    "emergency_exits":0,
    # Passive diagnostics. These never control execution.
    "last_model_decision":None,
    "last_trade_rejection":None,
    "last_approved_trade":None,
    "skip_reasons":{},
    "observability":{},
    "performance":{},
    "strategy_mode":strategy_mode.status(),
    "telegram_control":telegram_control.STATE,
    "micro_stats_6h":micro_stats.summary(6),
    "micro_second_shadow":micro_second_shadow.summary(),
    "micro_stream":micro_market_stream.health(),
    "crypto_shadow_lab":dict(crypto_shadow_lab.STATE),
    "adaptive_brain":adaptive_memory.load_brain(),
    "adaptive_learning_7d":adaptive_memory.summary(168),
    "adaptive_cost_today":adaptive_cost.usage_today(),
    "adaptive_trainer_7d":adaptive_trainer.summary(168),
    "multi_market_trainer_7d":multi_market_trainer.summary(168) if config.MULTI_MARKET_TRAINER_V3_ENABLED else {"status":"DISABLED"},
    "strategy_tournament_7d":strategy_tournament.summary(168) if config.STRATEGY_TOURNAMENT_V5_ENABLED else {"status":"DISABLED"},
    "alpha_factory":alpha_factory.summary(),
    "model_budget":model_budget.summary(),
    "market_scanner":market_scanner.summary(),
    "shadow_agent_council":agent_council.summary(),
    "fok_shadow_analyzer":fok_shadow_analyzer.summary(168),
    "exit_shadow_tournament":exit_shadow_tournament.summary(168),
}

def now():return datetime.now(timezone.utc)

def _trip_worker_circuit(consecutive,stage,error_type):
    """Latch new-entry pause; never disable position monitoring or exits."""
    active=consecutive>=config.WORKER_EXCEPTION_PAUSE_THRESHOLD
    state={"active":active,"consecutive":consecutive,
           "threshold":config.WORKER_EXCEPTION_PAUSE_THRESHOLD,
           "last_stage":stage,"last_error_type":error_type}
    if active and not (R.get("worker_exception_circuit") or {}).get("active"):
        # In-memory latch also works if the persistent mode file cannot write.
        R["worker_exception_circuit"]=state
        try:
            with strategy_mode.RUNTIME_LOCK:
                strategy_mode.set_mode("PAUSED",changed_by="WORKER_EXCEPTION_CIRCUIT")
        except Exception:
            state["mode_persist_failed"]=True
        try:
            telegram_notifier.notify_system(
                f"ASTRA ENTRY CIRCUIT PAUSED: {consecutive} worker errors. "
                f"Stage={stage}, type={error_type}. Position monitoring remains active.",level="RISK")
        except Exception:
            state["alert_failed"]=True
    return state

def _safe_mixed4h_research():
    """Passive research errors must not interrupt position monitoring."""
    try:
        return mixed4h_research.summary(168)
    except Exception as exc:
        return {"status":"ERROR","error_type":type(exc).__name__,"read_only":True}

def _safe_posttrade_incidents():
    """Passive incident forensics must never interrupt open-position monitoring."""
    try:
        closes=observability._dedupe_closes(
            observability._load_jsonl(observability.TRADE_JOURNAL)
        )
        return trade_incident_review.summarize(closes,limit=3)
    except Exception as exc:
        return {"status":"UNKNOWN","reason":"INCIDENT_REVIEW_FAILED",
                "error_type":type(exc).__name__,"read_only":True,
                "automatic_strategy_or_asset_changes":False}


def _heartbeat(mode):
    """Emit a compact, secret-free runtime summary for Railway diagnostics."""
    try:
        perf=observability.trade_performance(None)
        overall=perf.get("overall") or {}
        ms=micro_stats.summary(6)
        stream=micro_market_stream.health()
        second_shadow=micro_second_shadow.summary()
        af=alpha_factory.summary()
        diag24=observability.diagnostic_digest(24,5)
        funnel24=diag24.get("decision_funnel") or {}
        perf24=diag24.get("trade_performance") or {}
        payload={
            "event":"ASTRA_HEARTBEAT",
            "at_utc":now().isoformat(),
            "status":R.get("status"),
            "mode":mode,
            "execution_mode":config.EXECUTION_MODE,
            "decision_engine":bool(config.AUTO_DECISION),
            "trade_execution":bool(config.AUTO_PAPER_EXECUTION),
            "mode_controls":{
                "micro_new_entries_enabled":bool(config.MICRO_NEW_ENTRIES_ENABLED),
                "mtf_transition_enabled":bool(config.MTF_TRANSITION_ENABLED),
                "normal_entry_model_enabled":bool(config.AUTO_DECISION),
                "research":{
                    "crypto_shadow_lab":bool(config.CRYPTO_SHADOW_LAB_ENABLED),
                    "multi_market_trainer":bool(config.MULTI_MARKET_TRAINER_V3_ENABLED),
                    "strategy_tournament":bool(config.STRATEGY_TOURNAMENT_V5_ENABLED),
                    "alpha_factory":bool(config.ALPHA_FACTORY_ENABLED),
                    "shadow_council":bool(config.SHADOW_AGENT_COUNCIL_ENABLED),
                    "mtf_shadow_replay":bool(config.MTF_SHADOW_REPLAY_ENABLED),
                    "fok_shadow_analyzer":bool(config.FOK_SHADOW_ANALYZER_ENABLED),
                },
            },
            "worker_exception_circuit":R.get("worker_exception_circuit"),
            "equity_guard":R.get("equity_guard"),
            "multi_market_lab":"ON" if config.MULTI_MARKET_TRAINER_V3_ENABLED else "OFF",
            "micro":{
                "checks_6h":ms.get("checks",0),
                "model_calls_6h":ms.get("model_calls",0),
                "opened_6h":ms.get("opened_trades",0),
                "closed_6h":ms.get("closed_trades",0),
                "net_pnl_6h":ms.get("realized_net_pnl_usd",0),
                "top_blockers":list((ms.get("blockers") or {}).items())[:5],
                "stream_status":stream.get("status"),
                "stream_connected":stream.get("connected"),
                "second_shadow":second_shadow,
            },
            "trades_all":{
                "count":overall.get("trades",0),
                "wins":overall.get("wins",0),
                "losses":overall.get("losses",0),
                "win_rate_pct":overall.get("win_rate_pct",0),
                "net_pnl_usd":overall.get("net_pnl_usd",0),
                "profit_factor":overall.get("profit_factor"),
                "avg_r":overall.get("avg_r"),
            },
            "diagnostics_24h":{
                "decisions":funnel24.get("decisions",0),
                "model_calls":funnel24.get("model_calls",0),
                "model_skips":funnel24.get("model_skips",0),
                "model_waits":funnel24.get("model_waits",0),
                "opened_trades":funnel24.get("opened_trades",0),
                "skip_reasons":funnel24.get("skip_reasons") or {},
                "mtf_blockers":funnel24.get("mtf_blockers") or {},
                "mtf_shadow_replay":diag24.get("mtf_shadow_replay") or {},
                "trade_rejection_reasons":funnel24.get("trade_rejection_reasons") or {},
                "by_asset":funnel24.get("by_asset") or {},
                "trades_by_asset":(perf24.get("by_asset") or {}),
                "recent_closed":diag24.get("recent_closed") or [],
            },
            "mixed4h_research":_safe_mixed4h_research(),
            "stop_execution_audit":execution_audit.stop_exit_audit(diag24.get("recent_closed") or []),
            "posttrade_incident_review":_safe_posttrade_incidents(),
            "trade_setup_learning":{
                "status":"OBSERVATION_ONLY",
                "automatic_asset_or_setup_suppression":False,
                "cohorts":(perf.get("by_asset_setup_direction") or [])[:20],
            },
            "shadow_lab_status":crypto_shadow_lab.STATE.get("status"),
            "model_budget":{
                "status":model_budget.summary().get("status"),
                "model":model_budget.summary().get("model"),
                "daily":model_budget.summary().get("daily"),
                "circuit":model_budget.summary().get("circuit"),
            },
            "alpha_factory":{
                "status":af.get("status"),
                "evidence_rows":af.get("evidence_rows",0),
                "evaluated_genomes":af.get("evaluated_genomes",0),
                "shadow_champions":len(af.get("shadow_champions") or []),
                "promising":len(af.get("promising") or []),
                "stale":af.get("stale"),
            },
            "trade_universe":trade_universe.summary(),
            "market_scanner":{
                "status":market_scanner.summary().get("status"),
                "ranking":(market_scanner.summary().get("ranking") or [])[:5],
            },
            "shadow_agent_council":{
                "status":agent_council.summary().get("status"),
                "recorded_total":agent_council.summary().get("recorded_total",0),
                "status_counts":agent_council.summary().get("status_counts") or {},
                "strong_assets":agent_council.summary().get("strong_assets") or [],
            },
            "fok_shadow_analyzer":fok_shadow_analyzer.summary(24),
            "exit_shadow_tournament":exit_shadow_tournament.summary(168),
        }
        print(json.dumps(payload,ensure_ascii=False,separators=(",",":")),flush=True)
    except Exception as e:
        print(json.dumps({"event":"ASTRA_HEARTBEAT_ERROR","error":str(e)},separators=(",",":")),flush=True)

def refresh_observability():
    try:
        o=observability.health_summary()
        R["observability"]=o
        R["last_model_decision"]=o.get("last_model_decision")
        R["last_trade_rejection"]=o.get("last_trade_rejection")
        R["last_approved_trade"]=o.get("last_approved_trade")
        R["skip_reasons"]=o.get("skip_reasons",{})
        started=o.get("started_at_utc")
        R["performance"]=observability.trade_performance(started)
        R["micro_stats_6h"]=micro_stats.summary(6)
        R["micro_second_shadow"]=micro_second_shadow.summary()
        R["micro_stream"]=micro_market_stream.health()
        R["crypto_shadow_lab"]=dict(crypto_shadow_lab.STATE)
        R["decision_engine_enabled"]=bool(config.AUTO_DECISION)
        R["trade_execution_enabled"]=bool(config.AUTO_PAPER_EXECUTION)
        R["adaptive_brain"]=adaptive_memory.load_brain()
        R["adaptive_learning_7d"]=adaptive_memory.summary(168)
        R["adaptive_cost_today"]=adaptive_cost.usage_today()
        R["adaptive_trainer_7d"]=adaptive_trainer.summary(168)
        R["multi_market_trainer_7d"]=multi_market_trainer.summary(168) if config.MULTI_MARKET_TRAINER_V3_ENABLED else {"status":"DISABLED"}
        R["strategy_tournament_7d"]=strategy_tournament.summary(168) if config.STRATEGY_TOURNAMENT_V5_ENABLED else {"status":"DISABLED"}
        R["alpha_factory"]=alpha_factory.summary()
        R["model_budget"]=model_budget.summary()
        R["market_scanner"]=market_scanner.summary()
        R["shadow_agent_council"]=agent_council.summary()
        R["fok_shadow_analyzer"]=fok_shadow_analyzer.summary(168)
        R["exit_shadow_tournament"]=exit_shadow_tournament.summary(168)
    except Exception:
        # Diagnostics must never be able to degrade the trading worker.
        pass

class H(BaseHTTPRequestHandler):
    def _authorized(self):
        expected=str(config.MISSION_CONTROL_ACCESS_TOKEN or "")
        if not expected:
            return True
        auth=str(self.headers.get("Authorization") or "")
        supplied=auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        return bool(supplied) and hmac.compare_digest(supplied,expected)

    def _send_bytes(self,body,content_type,status=200):
        self.send_response(status)
        self.send_header("Content-Type",content_type)
        self.send_header("Content-Length",str(len(body)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("X-Frame-Options","DENY")
        self.end_headers()
        self.wfile.write(body)

    def _json(self,payload,status=200):
        self._send_bytes(
            json.dumps(payload,ensure_ascii=False,separators=(",",":")).encode(),
            "application/json; charset=utf-8",
            status,
        )

    def do_GET(self):
        path=self.path.split("?",1)[0]

        # Railway healthcheck stays public and deliberately contains no account,
        # trade, model, news or strategy research details.
        if path=="/health":
            return self._json({
                "status":R.get("status"),
                "started_at_utc":R.get("started_at_utc"),
                "mode":(R.get("strategy_mode") or {}).get("mode"),
                "at_utc":now().isoformat(),
            },200 if R.get("status")!="failed" else 503)

        if path=="/mission-control":
            if not config.MISSION_CONTROL_ENABLED:
                return self._json({"status":"DISABLED"},404)
            body=mission_control.html().encode("utf-8")
            return self._send_bytes(body,"text/html; charset=utf-8",200)

        if path not in {"/","/analytics","/api/mission-control"}:
            return self._json({"status":"NOT_FOUND"},404)

        if not self._authorized():
            return self._json({"status":"UNAUTHORIZED"},401)

        refresh_observability()
        if path=="/analytics":
            payload=observability.analytics_report()
        elif path=="/api/mission-control":
            if not config.MISSION_CONTROL_ENABLED:
                return self._json({"status":"DISABLED"},404)
            payload=mission_control.build_payload(R)
        else:
            payload=R
        return self._json(payload,200 if R.get("status")!="failed" else 503)

    def log_message(self,*args):return

def check_positions():
    return execution_router.sync_positions() if config.EXECUTION_MODE=="okx_demo" else position_monitor.check_once()

def main():
    threading.Thread(
        target=lambda:ThreadingHTTPServer(("0.0.0.0",config.PORT),H).serve_forever(),
        daemon=True
    ).start()
    if config.TELEGRAM_CONTROL_ENABLED:
        threading.Thread(target=telegram_control.run_forever,daemon=True).start()
    if config.CRYPTO_SHADOW_LAB_ENABLED:
        threading.Thread(target=crypto_shadow_lab.run_forever,daemon=True).start()
    if config.MULTI_MARKET_TRAINER_V3_ENABLED:
        threading.Thread(target=multi_market_trainer.run_forever,daemon=True).start()

    # Apply an explicit, non-secret key-rotation marker before model gating.
    # This may clear only a stale AUTH_ERROR circuit after an intentional key change.
    R["model_key_rotation"]=model_budget.apply_key_rotation_marker()
    paper_execution.init_state(config.INITIAL_EQUITY,False)
    R["status"]="ok"
    refresh_observability()

    last_news=0
    last_pos=0
    last_exit=0
    last_heartbeat=0
    last_decision={a:0 for a in config.ALLOWED_ASSETS}
    last_mode=None
    consecutive_failures=0

    while True:
        t=time.time()
        stage="loop_start"
        try:
            stage="strategy_mode"
            mode=strategy_mode.get_mode()
            if mode!=last_mode:
                last_decision={a:0 for a in config.ALLOWED_ASSETS}
                last_mode=mode
                if mode=="MICRO" and config.MICRO_NEW_ENTRIES_ENABLED:
                    micro_market_stream.ensure_started()

            R["strategy_mode"]=strategy_mode.status()
            R["telegram_control"]=dict(telegram_control.STATE)
            R["crypto_shadow_lab"]=dict(crypto_shadow_lab.STATE)
            high=set()

            if t-last_news>=config.NEWS_POLL_SECONDS:
                stage="news_poll"
                news_assets=trade_universe.assets_for_mode(mode)
                n=news_listener.poll_once(2,news_assets)
                R["last_news"]=n
                last_news=t

                for event in n.get("new_events",[]):
                    observability.record_news_event(event)

                reviews=[]
                for e in n.get("high_impact_new",[]):
                    if e.get("trade_usable"):
                        high.add(e.get("asset"))
                        if config.EMERGENCY_EXIT_ENABLED and config.EXECUTION_MODE=="okx_demo":
                            r=position_exit_guard.on_verified_news_event(e)
                            reviews.append(r)
                            if (
                                r.get("status")=="REVIEWED"
                                and bool((r.get("decision") or {}).get("model_called"))
                            ):
                                R["exit_model_calls"]+=1
                            if r.get("close",{}).get("status")=="CLOSE_SUBMITTED":
                                R["emergency_exits"]+=1
                if reviews:
                    R["last_news_exit_reviews"]=reviews[-10:]

            if t-last_pos>=config.POSITION_POLL_SECONDS:
                stage="position_sync"
                R["last_position_check"]=check_positions()
                if mode=="MICRO":
                    micro_second_shadow.evaluate_pending()
                stage="fok_shadow_evaluate"
                fok_shadow_analyzer.evaluate_due()
                stage="exit_shadow_evaluate"
                exit_shadow_tournament.evaluate_due()
                stage="refresh_observability"
                refresh_observability()
                last_pos=t

            if (
                config.EMERGENCY_EXIT_ENABLED
                and config.EXECUTION_MODE=="okx_demo"
                and t-last_exit>=config.EXIT_MARKET_CHECK_SECONDS
            ):
                r=position_exit_guard.check_market_exits()
                R["last_exit_check"]=r
                for item in r.get("results",[]):
                    if item.get("close",{}).get("status")=="CLOSE_SUBMITTED":
                        R["emergency_exits"]+=1
                last_exit=t

            # Only two tradable strategies exist now: NORMAL and MICRO.
            if (config.AUTO_DECISION and mode!="PAUSED"
                and (mode!="MICRO" or config.MICRO_NEW_ENTRIES_ENABLED)
                and not R["worker_exception_circuit"].get("active")):

                assets=trade_universe.assets_for_mode(mode)
                interval=config.MICRO_DECISION_INTERVAL_SECONDS if mode=="MICRO" else config.DECISION_INTERVAL_SECONDS
                gate_module=micro_decision_gate if mode=="MICRO" else decision_gate

                for a in assets:
                    if t-last_decision.get(a,0)>=interval or a in high:
                        stage=f"decision_prepare:{a}"
                        p=trade_cycle.prepare(a,12,mode)
                        account=p.get("account_state") or {}
                        R["equity_guard"]={
                            "verified":account.get("equity_verified"),
                            "source":account.get("equity_source"),
                            "reason":account.get("equity_error"),
                        }
                        stage=f"market_scanner:{a}"
                        market_scanner.observe(p)
                        stage=f"decision_gate:{a}"
                        gate=gate_module.evaluate(p,force_event=a in high)
                        stage=f"shadow_council:{a}"
                        council=agent_council.evaluate(p,gate)
                        agent_council.record(council,p)
                        p["shadow_council"]=council
                        R["market_scanner"]=market_scanner.summary()
                        R["shadow_agent_council"]=agent_council.summary()

                        if not gate["call_model"]:
                            d={"asset":a,"action":"WAIT","reason":gate["reason"],"gate":gate,"strategy_mode":mode}
                            x={"status":"NO_TRADE","reason":gate["reason"]}
                            R["model_skips"]+=1
                        else:
                            p["model_gate"]=gate
                            stage=f"model_decide:{a}"
                            d=decide(p)
                            d["gate"]=gate
                            d["strategy_mode"]=mode
                            model_called=bool(d.get("_model_called",False))
                            if model_called:
                                R["model_calls"]+=1
                            else:
                                R["model_skips"]+=1

                            stage=f"execution_or_shadow:{a}"
                            if not model_called:
                                # Budget/circuit/API failures fail closed. They are
                                # not allowed to fall through to order routing.
                                x={
                                    "status":"NO_TRADE",
                                    "reason":d.get("reason") or "MODEL_UNAVAILABLE",
                                }
                            elif mode=="MICRO" and gate.get("second_position_shadow"):
                                # Explicitly bypass execution: this experiment only
                                # measures whether a second position would add NET edge.
                                x=micro_second_shadow.consider(p,d,gate)
                            else:
                                x=trade_cycle.execute(d) if config.AUTO_PAPER_EXECUTION else {"status":"DECISION_ONLY"}

                        R["last_decisions"][a]={
                            "at_utc":now().isoformat(),
                            "strategy_mode":mode,
                            "decision":d,
                            "execution":x,
                            "shadow_council":council,
                        }
                        stage=f"observability:{a}"
                        observability.record_decision(p,gate,d,x,model_called=bool(d.get("_model_called",False)))
                        if mode=="MICRO":
                            stage=f"micro_stats:{a}"
                            micro_stats.record(p,gate,d,x,model_called=bool(d.get("_model_called",False)))
                        refresh_observability()
                        last_decision[a]=t

            R["status"]="ok"
            R["last_error"]=None
            consecutive_failures=0
            if not R["worker_exception_circuit"].get("active"):
                R["worker_exception_circuit"]["consecutive"]=0
            if t-last_heartbeat>=config.STATS_HEARTBEAT_SECONDS:
                _heartbeat(mode)
                last_heartbeat=t

        except Exception as e:
            consecutive_failures+=1
            if not R["worker_exception_circuit"].get("active"):
                R["worker_exception_circuit"]=_trip_worker_circuit(consecutive_failures,stage,type(e).__name__)
            R["status"]="degraded"
            R["last_error"]=traceback.format_exc()[-5000:]
            # Secret-free runtime diagnostic. Do not print request headers,
            # credentials or full decision payloads.
            print(json.dumps({
                "event":"ASTRA_WORKER_EXCEPTION",
                "at_utc":now().isoformat(),
                "stage":stage,
                "error_type":type(e).__name__,
                "error":str(e)[:1200],
            },ensure_ascii=False,separators=(",",":")),flush=True)

        time.sleep(config.WORKER_TICK_SECONDS)

if __name__=="__main__":
    main()

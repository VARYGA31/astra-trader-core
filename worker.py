#!/usr/bin/env python3
import json,time,threading,traceback
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from datetime import datetime,timezone

import config,news_listener,position_monitor,trade_cycle,paper_execution,execution_router,decision_gate,observability
import strategy_mode,micro_decision_gate,telegram_control,micro_stats,micro_market_stream,micro_second_shadow,crypto_shadow_lab
import adaptive_memory,adaptive_cost,adaptive_trainer,multi_market_trainer,strategy_tournament
import position_exit_guard
from astra_client import decide

R={
    "status":"starting",
    "started_at_utc":datetime.now(timezone.utc).isoformat(),
    "last_error":None,
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
}

def now():return datetime.now(timezone.utc)

def _heartbeat(mode):
    """Emit a compact, secret-free runtime summary for Railway diagnostics."""
    try:
        perf=observability.trade_performance(None)
        overall=perf.get("overall") or {}
        ms=micro_stats.summary(6)
        stream=micro_market_stream.health()
        second_shadow=micro_second_shadow.summary()
        payload={
            "event":"ASTRA_HEARTBEAT",
            "at_utc":now().isoformat(),
            "status":R.get("status"),
            "mode":mode,
            "execution_mode":config.EXECUTION_MODE,
            "decision_engine":bool(config.AUTO_DECISION),
            "trade_execution":bool(config.AUTO_PAPER_EXECUTION),
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
            "shadow_lab_status":crypto_shadow_lab.STATE.get("status"),
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
    except Exception:
        # Diagnostics must never be able to degrade the trading worker.
        pass

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        path=self.path.split("?",1)[0]
        if path not in {"/","/health","/analytics"}:
            self.send_response(404);self.end_headers();return

        if path=="/analytics":
            payload=observability.analytics_report()
        else:
            refresh_observability()
            payload=R

        b=json.dumps(payload,ensure_ascii=False).encode()
        self.send_response(200 if R["status"]!="failed" else 503)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(b)))
        self.end_headers();self.wfile.write(b)

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

    paper_execution.init_state(config.INITIAL_EQUITY,False)
    R["status"]="ok"
    refresh_observability()

    last_news=0
    last_pos=0
    last_exit=0
    last_heartbeat=0
    last_decision={a:0 for a in config.ALLOWED_ASSETS}
    last_mode=None

    while True:
        t=time.time()
        stage="loop_start"
        try:
            stage="strategy_mode"
            mode=strategy_mode.get_mode()
            if mode!=last_mode:
                last_decision={a:0 for a in config.ALLOWED_ASSETS}
                last_mode=mode
                if mode=="MICRO":
                    micro_market_stream.ensure_started()

            R["strategy_mode"]=strategy_mode.status()
            R["telegram_control"]=dict(telegram_control.STATE)
            R["crypto_shadow_lab"]=dict(crypto_shadow_lab.STATE)
            high=set()

            if t-last_news>=config.NEWS_POLL_SECONDS:
                stage="news_poll"
                news_assets=config.MICRO_ALLOWED_ASSETS if mode=="MICRO" else config.ALLOWED_ASSETS
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
                            if r.get("status")=="REVIEWED":
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
            if config.AUTO_DECISION and mode!="PAUSED":
                assets=config.MICRO_ALLOWED_ASSETS if mode=="MICRO" else config.ALLOWED_ASSETS
                interval=config.MICRO_DECISION_INTERVAL_SECONDS if mode=="MICRO" else config.DECISION_INTERVAL_SECONDS
                gate_module=micro_decision_gate if mode=="MICRO" else decision_gate

                for a in assets:
                    if t-last_decision.get(a,0)>=interval or a in high:
                        stage=f"decision_prepare:{a}"
                        p=trade_cycle.prepare(a,12,mode)
                        stage=f"decision_gate:{a}"
                        gate=gate_module.evaluate(p,force_event=a in high)

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
                            R["model_calls"]+=1
                            stage=f"execution_or_shadow:{a}"
                            if mode=="MICRO" and gate.get("second_position_shadow"):
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
                        }
                        stage=f"observability:{a}"
                        observability.record_decision(p,gate,d,x,model_called=bool(gate.get("call_model")))
                        if mode=="MICRO":
                            stage=f"micro_stats:{a}"
                            micro_stats.record(p,gate,d,x,model_called=bool(gate.get("call_model")))
                        refresh_observability()
                        last_decision[a]=t

            R["status"]="ok"
            R["last_error"]=None
            if t-last_heartbeat>=config.STATS_HEARTBEAT_SECONDS:
                _heartbeat(mode)
                last_heartbeat=t

        except Exception as e:
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

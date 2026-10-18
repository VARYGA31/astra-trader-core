#!/usr/bin/env python3
import json,time,threading,traceback
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from datetime import datetime,timezone

import config,news_listener,position_monitor,trade_cycle,paper_execution,execution_router,decision_gate,observability
import strategy_mode,scalp_decision_gate,telegram_control,scalp_stats
import adaptive_engine,adaptive_memory,adaptive_cost,adaptive_stats,adaptive_trainer,multi_market_trainer,strategy_tournament
import position_exit_guard
from astra_client import decide

R={
    "status":"starting",
    "started_at_utc":datetime.now(timezone.utc).isoformat(),
    "last_error":None,
    "execution_mode":config.EXECUTION_MODE,
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
    "scalp_stats_6h":scalp_stats.summary(6),
    "adaptive_brain":adaptive_memory.load_brain(),
    "adaptive_learning_7d":adaptive_memory.summary(168),
    "adaptive_cost_today":adaptive_cost.usage_today(),
    "adaptive_trainer_7d":adaptive_trainer.summary(168),
    "multi_market_trainer_7d":multi_market_trainer.summary(168) if config.MULTI_MARKET_TRAINER_V3_ENABLED else {"status":"DISABLED"},
    "strategy_tournament_7d":strategy_tournament.summary(168) if config.STRATEGY_TOURNAMENT_V5_ENABLED else {"status":"DISABLED"},
}
def now():return datetime.now(timezone.utc)

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
        R["scalp_stats_6h"]=scalp_stats.summary(6)
        R["adaptive_brain"]=adaptive_memory.load_brain()
        R["adaptive_learning_7d"]=adaptive_memory.summary(168)
        R["adaptive_cost_today"]=adaptive_cost.usage_today()
        R["adaptive_auto_stats_24h"]=adaptive_stats.summary(24)
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
    if config.MULTI_MARKET_TRAINER_V3_ENABLED:
        threading.Thread(target=multi_market_trainer.run_forever,daemon=True).start()

    paper_execution.init_state(config.INITIAL_EQUITY,False)
    R["status"]="ok"
    refresh_observability()
    last_news=0
    last_pos=0
    last_exit=0
    last_decision={a:0 for a in config.ALLOWED_ASSETS}
    last_auto_decision=0
    last_mode=None

    while True:
        t=time.time()
        try:
            mode=strategy_mode.get_mode()
            if mode!=last_mode:
                last_decision={a:0 for a in config.ALLOWED_ASSETS}
                last_mode=mode
            R["strategy_mode"]=strategy_mode.status()
            R["telegram_control"]=dict(telegram_control.STATE)
            high=set()

            if t-last_news>=config.NEWS_POLL_SECONDS:
                n=news_listener.poll_once(2)
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
                R["last_position_check"]=check_positions()
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

            if config.AUTO_DECISION and mode!="PAUSED":
                if mode=="AUTO":
                    force_auto=any(a in high for a in config.ADAPTIVE_ALLOWED_ASSETS)
                    if t-last_auto_decision>=config.ADAPTIVE_DECISION_INTERVAL_SECONDS or force_auto:
                        # Throttle before the model call so a transient API/JSON
                        # failure cannot trigger a retry storm every worker tick.
                        last_auto_decision=t
                        ar=adaptive_engine.run_once(force=force_auto)
                        adaptive_stats.record(ar)
                        R["last_adaptive_cycle"]={
                            "at_utc":now().isoformat(),
                            "status":ar.get("status"),
                            "reason":ar.get("reason"),
                            "result":ar.get("result"),
                            "execution":ar.get("execution"),
                            "learning":ar.get("learning"),
                            "trainer":{
                                "best":(ar.get("trainer") or {}).get("best"),
                                "summary":(ar.get("trainer") or {}).get("summary"),
                                "recorded":(ar.get("trainer") or {}).get("recorded"),
                                "evaluated":(ar.get("trainer") or {}).get("evaluated"),
                            } if ar.get("trainer") else None,
                            "tournament":{
                                "best":(ar.get("tournament") or {}).get("best"),
                                "summary":(ar.get("tournament") or {}).get("summary"),
                                "champions":len((ar.get("tournament") or {}).get("champions") or []),
                                "recorded":(ar.get("tournament") or {}).get("recorded"),
                                "evaluated":(ar.get("tournament") or {}).get("evaluated"),
                            } if ar.get("tournament") else None,
                        }
                        if ar.get("status")=="OK":
                            R["model_calls"]+=1
                            d=ar.get("decision") or {}
                            x=ar.get("execution") or {"status":"NO_TRADE","reason":"ADAPTIVE_WAIT"}
                            best=(ar.get("result") or {}).get("best_opportunity") or {}
                            a=str(best.get("asset") or d.get("asset") or "MULTI").upper()
                            R["last_decisions"]["AUTO"]={
                                "at_utc":now().isoformat(),
                                "strategy_mode":"AUTO",
                                "decision":d,
                                "execution":x,
                                "brain":ar.get("result"),
                            }
                            p=(ar.get("packages") or {}).get(a)
                            if p:
                                gate={
                                    "call_model":True,
                                    "reason":"ADAPTIVE_MULTI_ASSET",
                                    "allowed_direction":best.get("action") if best.get("action") in {"LONG","SHORT"} else None,
                                    "mtf_quality":best.get("setup_quality"),
                                    "mtf_mode":best.get("strategy"),
                                    "mtf":{
                                        "passed":best.get("action") in {"LONG","SHORT"},
                                        "direction":best.get("action"),
                                        "mode":best.get("strategy"),
                                        "quality":best.get("setup_quality"),
                                        "minimum_quality":(
                                            config.ADAPTIVE_MIN_SCALP_QUALITY
                                            if best.get("strategy")=="SCALP"
                                            else config.ADAPTIVE_MIN_NORMAL_QUALITY
                                        ),
                                    },
                                }
                                observability.record_decision(p,gate,d,x,model_called=True)
                        else:
                            R["model_skips"]+=1
                        refresh_observability()
                else:
                    assets=config.SCALP_ALLOWED_ASSETS if mode=="SCALP" else config.ALLOWED_ASSETS
                    interval=config.SCALP_DECISION_INTERVAL_SECONDS if mode=="SCALP" else config.DECISION_INTERVAL_SECONDS
                    gate_module=scalp_decision_gate if mode=="SCALP" else decision_gate
                    for a in assets:
                        if t-last_decision.get(a,0)>=interval or a in high:
                            p=trade_cycle.prepare(a,12,mode)
                            gate=gate_module.evaluate(p,force_event=a in high)

                            if not gate["call_model"]:
                                d={"asset":a,"action":"WAIT","reason":gate["reason"],"gate":gate,"strategy_mode":mode}
                                x={"status":"NO_TRADE","reason":gate["reason"]}
                                R["model_skips"]+=1
                            else:
                                p["model_gate"]=gate
                                d=decide(p)
                                d["gate"]=gate
                                d["strategy_mode"]=mode
                                R["model_calls"]+=1
                                x=trade_cycle.execute(d) if config.AUTO_PAPER_EXECUTION else {"status":"DECISION_ONLY"}

                            R["last_decisions"][a]={
                                "at_utc":now().isoformat(),
                                "strategy_mode":mode,
                                "decision":d,
                                "execution":x,
                            }
                            observability.record_decision(p,gate,d,x,model_called=bool(gate.get("call_model")))
                            if mode=="SCALP":
                                scalp_stats.record(p,gate,d,x,model_called=bool(gate.get("call_model")))
                            refresh_observability()
                            last_decision[a]=t

            R["status"]="ok"
            R["last_error"]=None

        except Exception:
            R["status"]="degraded"
            R["last_error"]=traceback.format_exc()[-5000:]

        time.sleep(config.WORKER_TICK_SECONDS)

if __name__=="__main__":
    main()

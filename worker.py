#!/usr/bin/env python3
import json,time,threading,traceback
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from datetime import datetime,timezone

import config,news_listener,position_monitor,trade_cycle,paper_execution,execution_router,decision_gate
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
}
def now():return datetime.now(timezone.utc)

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in {"/","/health"}:
            self.send_response(404);self.end_headers();return
        b=json.dumps(R,ensure_ascii=False).encode()
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

    paper_execution.init_state(config.INITIAL_EQUITY,False)
    R["status"]="ok"
    last_news=0
    last_pos=0
    last_exit=0
    last_decision={a:0 for a in config.ALLOWED_ASSETS}

    while True:
        t=time.time()
        try:
            high=set()

            if t-last_news>=config.NEWS_POLL_SECONDS:
                n=news_listener.poll_once(2)
                R["last_news"]=n
                last_news=t

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

            if config.AUTO_DECISION:
                for a in config.ALLOWED_ASSETS:
                    if t-last_decision[a]>=config.DECISION_INTERVAL_SECONDS or a in high:
                        p=trade_cycle.prepare(a,12)
                        gate=decision_gate.evaluate(p,force_event=a in high)

                        if not gate["call_model"]:
                            d={"asset":a,"action":"WAIT","reason":gate["reason"],"gate":gate}
                            x={"status":"NO_TRADE","reason":gate["reason"]}
                            R["model_skips"]+=1
                        else:
                            d=decide(p)
                            d["gate"]=gate
                            R["model_calls"]+=1
                            x=trade_cycle.execute(d) if config.AUTO_PAPER_EXECUTION else {"status":"DECISION_ONLY"}

                        R["last_decisions"][a]={
                            "at_utc":now().isoformat(),
                            "decision":d,
                            "execution":x,
                        }
                        last_decision[a]=t

            R["status"]="ok"
            R["last_error"]=None

        except Exception:
            R["status"]="degraded"
            R["last_error"]=traceback.format_exc()[-5000:]

        time.sleep(config.WORKER_TICK_SECONDS)

if __name__=="__main__":
    main()

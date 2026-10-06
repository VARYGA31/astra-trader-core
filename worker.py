#!/usr/bin/env python3
import json,time,threading,traceback
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from datetime import datetime,timezone
import config,news_listener,position_monitor,trade_cycle,paper_execution,execution_router
from astra_client import decide

R={"status":"starting","started_at_utc":datetime.now(timezone.utc).isoformat(),"last_error":None,
   "execution_mode":config.EXECUTION_MODE,"last_news":None,"last_position_check":None,"last_decisions":{}}

def now():return datetime.now(timezone.utc)
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in {"/","/health"}:self.send_response(404);self.end_headers();return
        b=json.dumps(R,ensure_ascii=False).encode();self.send_response(200 if R["status"]!="failed" else 503)
        self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b)
    def log_message(self,*args):return

def check_positions():
    if config.EXECUTION_MODE=="bybit_testnet":
        return execution_router.sync_positions()
    return position_monitor.check_once()

def main():
    threading.Thread(target=lambda:ThreadingHTTPServer(("0.0.0.0",config.PORT),H).serve_forever(),daemon=True).start()
    paper_execution.init_state(config.INITIAL_EQUITY,False);R["status"]="ok"
    last_news=0;last_pos=0;last_decision={a:0 for a in config.ALLOWED_ASSETS}
    while True:
        t=time.time()
        try:
            high_trigger=set()
            if t-last_news>=config.NEWS_POLL_SECONDS:
                n=news_listener.poll_once(2);R["last_news"]=n;last_news=t
                for e in n.get("high_impact_new",[]):high_trigger.add(e.get("asset"))
            if t-last_pos>=config.POSITION_POLL_SECONDS:
                R["last_position_check"]=check_positions();last_pos=t
            if config.AUTO_DECISION:
                for a in config.ALLOWED_ASSETS:
                    if t-last_decision[a]>=config.DECISION_INTERVAL_SECONDS or a in high_trigger:
                        p=trade_cycle.prepare(a,12)
                        if any([p["guards"].get("market_stale"),not p["guards"].get("market_ok"),not p["guards"].get("news_ok"),
                                not p["guards"].get("critical_news_verified"),p["guards"].get("trading_halted")]):
                            d={"asset":a,"action":"WAIT","reason":"GUARD_BLOCK"};x={"status":"NO_TRADE","reason":"GUARD_BLOCK"}
                        else:
                            d=decide(p)
                            x=trade_cycle.execute(d) if config.AUTO_PAPER_EXECUTION else {"status":"DECISION_ONLY"}
                        R["last_decisions"][a]={"at_utc":now().isoformat(),"decision":d,"execution":x};last_decision[a]=t
            R["status"]="ok";R["last_error"]=None
        except Exception:
            R["status"]="degraded";R["last_error"]=traceback.format_exc()[-5000:]
        time.sleep(config.WORKER_TICK_SECONDS)
if __name__=="__main__":main()

#!/usr/bin/env python3
import os,sys,json,tempfile,subprocess
from pathlib import Path

def offline():
    td=tempfile.mkdtemp(prefix="astra_preflight_");os.environ["STATE_DIR"]=td
    import importlib,config
    config.STATE_DIR=td
    import paper_execution,risk_engine,cooldown,trade_journal,news_verifier
    assert paper_execution.init_state(100,True)["status"]=="INITIALIZED"
    r=risk_engine.evaluate({"asset":"BTC","action":"LONG","equity":100,"initial_equity":100,"daily_pnl":0,"open_positions":0,
        "current_exposure_usd":0,"entry":100,"stop_loss":98,"confidence":80,"data_quality":"OK","critical_news_verified":True,
        "volatility_regime":"NORMAL","leverage":5})
    assert r["status"]=="APPROVED";r["take_profit_1"]=104;r["take_profit_2"]=108
    p=Path(td)/"risk.json";p.write_text(json.dumps(r),encoding="utf-8")
    op=paper_execution.open_position(p);pid=op["position"]["id"];assert op["status"]=="PAPER_OPENED"
    assert paper_execution.partial_close(pid,104,.5,"TAKE_PROFIT_1")["status"]=="PAPER_PARTIAL_CLOSE"
    assert paper_execution.partial_close(pid,108,1,"TAKE_PROFIT_2")["status"]=="PAPER_CLOSED"
    assert cooldown.set_cooldown("BTC",60,"TEST")["active"]
    assert trade_journal.summary()["overall"]["trades"]==1
    h=risk_engine.evaluate({"asset":"BTC","action":"LONG","equity":75,"initial_equity":100,"daily_pnl":0,"open_positions":0,
        "current_exposure_usd":0,"entry":100,"stop_loss":98,"confidence":80,"data_quality":"OK","critical_news_verified":True,
        "volatility_regime":"NORMAL","leverage":5})
    assert h["reason"]=="MAX_DRAWDOWN_REACHED"
    ev=[{"title":"Major exchange hacked","source_id":"telegram_markettwits","verification_status":"DISCOVERY_ONLY","impact_hint":"HIGH"},
        {"title":"Major exchange hacked in security breach","source_id":"coindesk","verification_status":"SECONDARY","impact_hint":"HIGH"}]
    news_verifier.apply_corroboration(ev);assert ev[0]["trade_usable"] is True
    return ["risk","paper_open","partial_tp1","tp2","cooldown","journal","kill_switch","news_corroboration"]

def network():
    checks=[];fail=[]
    import market_snapshot,news_snapshot,telegram_markettwits,decision_context
    for a in ("BTC","ETH","GRAM"):
        m=market_snapshot.snapshot(a)
        if m.get("data_quality",{}).get("status")=="FAILED":fail.append(f"market_{a}")
        else:checks.append(f"market_{a}")
        n=news_snapshot.snapshot(a,12)
        if n.get("status")=="FAILED":fail.append(f"news_{a}")
        else:checks.append(f"news_{a}")
        c=decision_context.build(a,12)
        if c.get("status")!="OK":fail.append(f"context_{a}")
        else:checks.append(f"context_{a}")
    try:
        t=telegram_markettwits.fetch()
        if not t:fail.append("telegram_markettwits_empty")
        else:checks.append("telegram_markettwits")
    except Exception:
        fail.append("telegram_markettwits")
    return checks,fail

off=offline();out={"status":"OFFLINE_OK","offline_checks":off}
if "--network" in sys.argv:
    c,f=network();out["network_checks"]=c;out["network_failures"]=f;out["status"]="ASTRA_FULL_PREFLIGHT_OK" if not f else "NETWORK_PARTIAL"
print(json.dumps(out,ensure_ascii=False,indent=2))

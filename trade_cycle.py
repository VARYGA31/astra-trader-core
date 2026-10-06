#!/usr/bin/env python3
import sys, json, subprocess, tempfile, os
from datetime import datetime, timezone

ALLOWED = {"BTC", "ETH", "GRAM"}
WORKSPACE = "/workspace"

def run_json(args, timeout=90):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        return {"_status":"FAILED","_returncode":p.returncode,"_stderr":p.stderr[-2000:],"stdout":p.stdout[-2000:]}
    try:
        return json.loads(p.stdout)
    except Exception as e:
        return {"_status":"FAILED","_error":f"JSONDecodeError: {e}","_stdout":p.stdout[-2000:]}

def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def prepare(asset, hours):
    if asset not in ALLOWED:
        return {"status":"TRADE_NOT_ALLOWED","requested_asset":asset,"allowed_assets":sorted(ALLOWED)}
    ctx = run_json(["python", f"{WORKSPACE}/decision_context.py", asset, str(hours)])
    if ctx.get("_status") == "FAILED":
        return {"status":"FAILED","stage":"decision_context","detail":ctx}
    paper = run_json(["python", f"{WORKSPACE}/paper_execution.py", "status"])
    if paper.get("_status") == "FAILED":
        return {"status":"FAILED","stage":"paper_status","detail":paper}

    package = {
        "status":"READY_FOR_ASTRA",
        "asset":asset,
        "generated_at_utc":datetime.now(timezone.utc).isoformat(),
        "decision_context":ctx,
        "account_state":{
            "initial_equity":paper.get("initial_equity"),
            "equity":paper.get("account_equity"),
            "open_positions":paper.get("open_positions_count"),
            "current_exposure_usd":paper.get("current_exposure_usd"),
            "trading_halted":paper.get("trading_halted"),
        },
        "required_astra_output":{
            "asset":"BTC|ETH|GRAM",
            "action":"LONG|SHORT|WAIT",
            "entry":"number|null",
            "stop_loss":"number|null",
            "take_profit_1":"number|null",
            "take_profit_2":"number|null",
            "confidence":"0-100",
            "data_quality":"OK|PARTIAL|FAILED",
            "high_impact_news_verified":"boolean",
            "volatility_regime":"LOW|NORMAL|HIGH|EXTREME",
            "leverage":"3-5",
            "reason":"short string"
        }
    }
    out_path = f"{WORKSPACE}/astra_input_{asset}.json"
    write_json(out_path, package)
    package["astra_input_file"] = out_path
    return package

def execute(decision_path):
    with open(decision_path, "r", encoding="utf-8") as f:
        decision = json.load(f)

    asset = str(decision.get("asset","")).upper()
    action = str(decision.get("action","")).upper()
    if asset not in ALLOWED:
        return {"status":"REJECTED","stage":"precheck","reason":"TRADE_NOT_ALLOWED"}
    if action == "WAIT":
        return {"status":"NO_TRADE","reason":"ASTRA_WAIT"}
    if action not in {"LONG","SHORT"}:
        return {"status":"REJECTED","stage":"precheck","reason":"INVALID_ACTION"}

    paper = run_json(["python", f"{WORKSPACE}/paper_execution.py", "status"])
    if paper.get("_status") == "FAILED":
        return {"status":"FAILED","stage":"paper_status","detail":paper}
    if paper.get("trading_halted"):
        return {"status":"REJECTED","stage":"precheck","reason":"TRADING_HALTED"}

    risk_input = {
        "asset":asset,
        "action":action,
        "equity":paper.get("account_equity",100),
        "initial_equity":paper.get("initial_equity",100),
        "daily_pnl":0,
        "open_positions":paper.get("open_positions_count",0),
        "current_exposure_usd":paper.get("current_exposure_usd",0),
        "entry":decision.get("entry"),
        "stop_loss":decision.get("stop_loss"),
        "confidence":decision.get("confidence",0),
        "data_quality":decision.get("data_quality","FAILED"),
        "high_impact_news_verified":decision.get("high_impact_news_verified",False),
        "volatility_regime":decision.get("volatility_regime","NORMAL"),
        "leverage":decision.get("leverage",3),
    }

    risk_in_path = f"{WORKSPACE}/risk_input_{asset}.json"
    write_json(risk_in_path, risk_input)
    risk = run_json(["python", f"{WORKSPACE}/risk_engine.py", risk_in_path])
    if risk.get("_status") == "FAILED":
        return {"status":"FAILED","stage":"risk_engine","detail":risk}

    risk_out_path = f"{WORKSPACE}/risk_output_{asset}.json"
    write_json(risk_out_path, risk)

    if risk.get("status") != "APPROVED":
        return {"status":"REJECTED","stage":"risk_engine","risk":risk}

    paper_open = run_json(["python", f"{WORKSPACE}/paper_execution.py", "open", risk_out_path])
    if paper_open.get("_status") == "FAILED":
        return {"status":"FAILED","stage":"paper_execution","detail":paper_open}

    return {
        "status":paper_open.get("status"),
        "decision":decision,
        "risk":risk,
        "paper_execution":paper_open,
    }

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error":"usage: prepare ASSET [hours] | execute decision.json"}, ensure_ascii=False))
        raise SystemExit(2)
    cmd = sys.argv[1].lower()
    if cmd == "prepare":
        asset = (sys.argv[2] if len(sys.argv)>2 else "BTC").upper()
        hours = int(sys.argv[3]) if len(sys.argv)>3 else 12
        result = prepare(asset,hours)
    elif cmd == "execute":
        if len(sys.argv)<3:
            raise SystemExit("execute requires decision json path")
        result = execute(sys.argv[2])
    else:
        result = {"status":"REJECTED","reason":"UNKNOWN_COMMAND"}
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))

if __name__ == "__main__":
    main()

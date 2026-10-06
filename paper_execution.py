#!/usr/bin/env python3
import sys, json, os, uuid
from datetime import datetime, timezone

STATE_FILE = "/workspace/paper_state.json"
ALLOWED_ASSETS = {"BTC", "ETH", "GRAM"}

def now_utc():
    return datetime.now(timezone.utc).isoformat()

def load_state():
    if not os.path.exists(STATE_FILE):
        return {
            "initial_equity": 100.0,
            "account_equity": 100.0,
            "free_cash": 100.0,
            "realized_pnl": 0.0,
            "open_positions": [],
            "closed_positions": [],
            "trading_halted": False,
            "created_at_utc": now_utc(),
            "updated_at_utc": now_utc(),
        }
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state):
    state["updated_at_utc"] = now_utc()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def drawdown_pct(state):
    init_eq = float(state["initial_equity"])
    eq = float(state["account_equity"])
    return max(0.0, (init_eq - eq) / init_eq) if init_eq > 0 else 1.0

def maybe_halt(state):
    if drawdown_pct(state) >= 0.25:
        state["trading_halted"] = True
    return state["trading_halted"]

def init_state(initial_equity=100.0, force=False):
    if os.path.exists(STATE_FILE) and not force:
        return {"status":"EXISTS","state_file":STATE_FILE,"state":load_state()}
    eq = float(initial_equity)
    state = {
        "initial_equity": eq,
        "account_equity": eq,
        "free_cash": eq,
        "realized_pnl": 0.0,
        "open_positions": [],
        "closed_positions": [],
        "trading_halted": False,
        "created_at_utc": now_utc(),
        "updated_at_utc": now_utc(),
    }
    save_state(state)
    return {"status":"INITIALIZED","state_file":STATE_FILE,"state":state}

def open_position(risk_json_path):
    state = load_state()
    if maybe_halt(state):
        save_state(state)
        return {"status":"REJECTED","reason":"TRADING_HALTED","state":state}

    with open(risk_json_path, "r", encoding="utf-8") as f:
        risk = json.load(f)

    if risk.get("status") != "APPROVED":
        return {"status":"REJECTED","reason":"RISK_NOT_APPROVED","risk_status":risk.get("status")}

    asset = str(risk.get("asset","")).upper()
    action = str(risk.get("action","")).upper()

    if asset not in ALLOWED_ASSETS:
        return {"status":"REJECTED","reason":"TRADE_NOT_ALLOWED"}
    if action not in {"LONG","SHORT"}:
        return {"status":"REJECTED","reason":"INVALID_ACTION"}
    if len(state["open_positions"]) >= 2:
        return {"status":"REJECTED","reason":"MAX_OPEN_POSITIONS"}
    if any(p["asset"] == asset for p in state["open_positions"]):
        return {"status":"REJECTED","reason":"DUPLICATE_ASSET_POSITION"}

    notional = float(risk["position_notional_usd"])
    leverage = float(risk["leverage"])
    margin = float(risk["margin_required_usd"])

    if margin > float(state["free_cash"]):
        return {"status":"REJECTED","reason":"INSUFFICIENT_FREE_CASH"}

    pos = {
        "id": str(uuid.uuid4())[:8],
        "asset": asset,
        "side": action,
        "entry": float(risk["entry"]),
        "stop_loss": float(risk["stop_loss"]),
        "notional_usd": notional,
        "leverage": leverage,
        "margin_used_usd": margin,
        "max_planned_loss_usd": float(risk["actual_risk_usd"]),
        "opened_at_utc": now_utc(),
        "status": "OPEN",
    }

    state["free_cash"] -= margin
    state["open_positions"].append(pos)
    save_state(state)

    return {
        "status":"PAPER_OPENED",
        "position":pos,
        "account_equity":state["account_equity"],
        "free_cash_remaining":state["free_cash"],
        "state_file":STATE_FILE,
    }

def close_position(position_id, exit_price):
    state = load_state()
    pos = next((p for p in state["open_positions"] if p["id"] == position_id), None)
    if not pos:
        return {"status":"REJECTED","reason":"POSITION_NOT_FOUND"}

    entry = float(pos["entry"])
    exit_price = float(exit_price)
    notional = float(pos["notional_usd"])

    if pos["side"] == "LONG":
        pnl = notional * ((exit_price - entry) / entry)
    else:
        pnl = notional * ((entry - exit_price) / entry)

    state["free_cash"] += float(pos["margin_used_usd"]) + pnl
    state["account_equity"] += pnl
    state["realized_pnl"] += pnl

    pos["exit_price"] = exit_price
    pos["realized_pnl_usd"] = pnl
    pos["closed_at_utc"] = now_utc()
    pos["status"] = "CLOSED"

    state["open_positions"] = [p for p in state["open_positions"] if p["id"] != position_id]
    state["closed_positions"].append(pos)
    maybe_halt(state)
    save_state(state)

    return {
        "status":"PAPER_CLOSED",
        "position":pos,
        "account_equity":state["account_equity"],
        "free_cash":state["free_cash"],
        "realized_pnl_total":state["realized_pnl"],
        "drawdown_pct":drawdown_pct(state),
        "trading_halted":state["trading_halted"],
    }

def status():
    state = load_state()
    maybe_halt(state)
    save_state(state)
    current_exposure = sum(float(p["notional_usd"]) for p in state["open_positions"])
    margin_used = sum(float(p["margin_used_usd"]) for p in state["open_positions"])
    return {
        "status":"OK",
        "initial_equity":state["initial_equity"],
        "account_equity":state["account_equity"],
        "free_cash":state["free_cash"],
        "realized_pnl":state["realized_pnl"],
        "open_positions":state["open_positions"],
        "open_positions_count":len(state["open_positions"]),
        "current_exposure_usd":current_exposure,
        "margin_used_usd":margin_used,
        "closed_positions_count":len(state["closed_positions"]),
        "drawdown_pct":drawdown_pct(state),
        "trading_halted":state["trading_halted"],
        "state_file":STATE_FILE,
    }

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error":"usage: init|status|open|close"}, ensure_ascii=False))
        raise SystemExit(2)
    cmd = sys.argv[1].lower()
    if cmd == "init":
        eq = float(sys.argv[2]) if len(sys.argv) > 2 else 100.0
        force = "--force" in sys.argv
        result = init_state(eq, force)
    elif cmd == "status":
        result = status()
    elif cmd == "open":
        if len(sys.argv) < 3:
            raise SystemExit("open requires risk json path")
        result = open_position(sys.argv[2])
    elif cmd == "close":
        if len(sys.argv) < 4:
            raise SystemExit("close requires position_id and exit_price")
        result = close_position(sys.argv[2], float(sys.argv[3]))
    else:
        result = {"status":"REJECTED","reason":"UNKNOWN_COMMAND"}
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))

if __name__ == "__main__":
    main()

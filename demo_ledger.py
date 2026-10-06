#!/usr/bin/env python3
import json
from pathlib import Path
from datetime import datetime, timezone
import config

FILE = Path(config.STATE_DIR) / "demo_ledger.json"

def now():
    return datetime.now(timezone.utc)

def today():
    return now().date().isoformat()

def base():
    return {
        "initial_equity": config.INITIAL_EQUITY,
        "realized_pnl": 0.0,
        "daily_realized_pnl": 0.0,
        "daily_pnl_date": today(),
        "trading_halted": False,
        "closed_trades": 0,
        "updated_at_utc": now().isoformat(),
    }

def load():
    try:
        s = json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        s = base()
    if s.get("daily_pnl_date") != today():
        s["daily_realized_pnl"] = 0.0
        s["daily_pnl_date"] = today()
    return s

def save(s):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    s["updated_at_utc"] = now().isoformat()
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(FILE)

def status():
    s = load()
    equity = float(s["initial_equity"]) + float(s["realized_pnl"])
    dd = max(0.0, (float(s["initial_equity"]) - equity) / float(s["initial_equity"]))
    if dd >= config.MAX_DRAWDOWN_PCT:
        s["trading_halted"] = True
    save(s)
    return {
        "initial_equity": float(s["initial_equity"]),
        "equity": equity,
        "realized_pnl": float(s["realized_pnl"]),
        "daily_pnl": float(s["daily_realized_pnl"]),
        "drawdown_pct": dd,
        "trading_halted": bool(s["trading_halted"]),
        "closed_trades": int(s["closed_trades"]),
    }

def apply_closed_trade(pnl_usd):
    s = load()
    pnl = float(pnl_usd or 0.0)
    s["realized_pnl"] = float(s["realized_pnl"]) + pnl
    s["daily_realized_pnl"] = float(s["daily_realized_pnl"]) + pnl
    s["closed_trades"] = int(s["closed_trades"]) + 1
    save(s)
    return status()

if __name__ == "__main__":
    print(json.dumps(status(), ensure_ascii=False))

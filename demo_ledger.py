#!/usr/bin/env python3
import json
import threading
from pathlib import Path
from datetime import datetime, timezone
import config

FILE = Path(config.STATE_DIR) / "demo_ledger.json"
LOCK = threading.RLock()

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

def _load_unlocked():
    try:
        s = json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        s = base()
    if s.get("daily_pnl_date") != today():
        s["daily_realized_pnl"] = 0.0
        s["daily_pnl_date"] = today()
    return s

def load():
    with LOCK:
        return _load_unlocked()

def _save_unlocked(s):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    s["updated_at_utc"] = now().isoformat()
    # Use a unique temp file so even accidental cross-thread/process overlap
    # cannot make one writer remove another writer's temporary path.
    tmp = FILE.with_name(
        f"{FILE.name}.{threading.get_ident()}.{int(now().timestamp()*1_000_000)}.tmp"
    )
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(FILE)

def save(s):
    with LOCK:
        _save_unlocked(s)

def _status_unlocked():
    s = _load_unlocked()
    equity = float(s["initial_equity"]) + float(s["realized_pnl"])
    dd = max(0.0, (float(s["initial_equity"]) - equity) / float(s["initial_equity"]))
    if dd >= config.MAX_DRAWDOWN_PCT:
        s["trading_halted"] = True
    _save_unlocked(s)
    return {
        "initial_equity": float(s["initial_equity"]),
        "equity": equity,
        "realized_pnl": float(s["realized_pnl"]),
        "daily_pnl": float(s["daily_realized_pnl"]),
        "drawdown_pct": dd,
        "trading_halted": bool(s["trading_halted"]),
        "closed_trades": int(s["closed_trades"]),
    }

def status():
    with LOCK:
        return _status_unlocked()

def apply_closed_trade(pnl_usd):
    with LOCK:
        s = _load_unlocked()
        pnl = float(pnl_usd or 0.0)
        s["realized_pnl"] = float(s["realized_pnl"]) + pnl
        s["daily_realized_pnl"] = float(s["daily_realized_pnl"]) + pnl
        s["closed_trades"] = int(s["closed_trades"]) + 1
        _save_unlocked(s)
        return _status_unlocked()

def halt_for_mark_to_market_drawdown():
    """Make a breached exchange-equity drawdown halt sticky across redeploys."""
    with LOCK:
        s=_load_unlocked()
        s["trading_halted"]=True
        _save_unlocked(s)

if __name__ == "__main__":
    print(json.dumps(status(), ensure_ascii=False))

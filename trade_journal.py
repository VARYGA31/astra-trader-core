#!/usr/bin/env python3
import json
import math
import statistics
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

import config

STATE_DIR = Path(config.STATE_DIR)
JOURNAL_FILE = STATE_DIR / "trade_journal.jsonl"
PAPER_STATE = STATE_DIR / "paper_state.json"

def now_utc():
    return datetime.now(timezone.utc).isoformat()

def read_jsonl(path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out

def closed_positions():
    if not PAPER_STATE.exists():
        return []
    try:
        state = json.loads(PAPER_STATE.read_text(encoding="utf-8"))
        return state.get("closed_positions", [])
    except Exception:
        return []

def calc_stats(trades):
    pnls = [float(t.get("realized_pnl_usd", 0.0)) for t in trades]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    win_rate = (len(wins)/len(pnls)) if pnls else 0.0
    avg_win = statistics.mean(wins) if wins else 0.0
    avg_loss = statistics.mean(losses) if losses else 0.0
    expectancy = statistics.mean(pnls) if pnls else 0.0
    profit_factor = (gross_profit/gross_loss) if gross_loss > 0 else (math.inf if gross_profit > 0 else None)

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        dd = peak - equity
        max_dd = max(max_dd, dd)

    return {
        "trades": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "gross_profit_usd": gross_profit,
        "gross_loss_usd": gross_loss,
        "avg_win_usd": avg_win,
        "avg_loss_usd": avg_loss,
        "expectancy_usd_per_trade": expectancy,
        "profit_factor": profit_factor,
        "max_drawdown_usd_from_trade_sequence": max_dd,
        "net_pnl_usd": sum(pnls),
    }

def summary():
    trades = closed_positions()
    by_asset = defaultdict(list)
    for t in trades:
        by_asset[t.get("asset", "UNKNOWN")].append(t)

    out = {
        "generated_at_utc": now_utc(),
        "overall": calc_stats(trades),
        "by_asset": {asset: calc_stats(items) for asset, items in by_asset.items()},
        "recent_closed_positions": trades[-20:],
        "journal_events": read_jsonl(JOURNAL_FILE)[-50:],
    }
    return out

def append_event(event):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    event = {"timestamp_utc": now_utc(), **event}
    with JOURNAL_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return {"status": "APPENDED", "event": event}

def main():
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "append":
        payload = json.loads(sys.stdin.read() or "{}")
        print(json.dumps(append_event(payload), ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(summary(), ensure_ascii=False, separators=(",", ":")))

if __name__ == "__main__":
    main()

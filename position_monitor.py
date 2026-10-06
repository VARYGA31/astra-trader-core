#!/usr/bin/env python3
import json
import subprocess
import time
from pathlib import Path
from datetime import datetime, timezone

import config

BASE = Path(__file__).resolve().parent
STATE_DIR = Path(config.STATE_DIR)
JOURNAL_FILE = STATE_DIR / "trade_journal.jsonl"

def now_utc():
    return datetime.now(timezone.utc).isoformat()

def run_json(args, timeout=60):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        return {
            "_status": "FAILED",
            "_returncode": p.returncode,
            "_stderr": p.stderr[-2000:],
            "_stdout": p.stdout[-2000:],
        }
    try:
        return json.loads(p.stdout)
    except Exception as e:
        return {
            "_status": "FAILED",
            "_error": f"JSONDecodeError: {e}",
            "_stdout": p.stdout[-2000:],
        }

def append_journal(event):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with JOURNAL_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

def get_spot_price(asset):
    market = run_json(["python", str(BASE / "market_snapshot.py"), asset], timeout=90)
    if market.get("_status") == "FAILED":
        return None, market
    price = market.get("spot", {}).get("price")
    if price is None:
        return None, market
    return float(price), market

def should_close(position, price):
    side = position["side"]
    stop = float(position["stop_loss"])
    tp1 = position.get("take_profit_1")
    tp2 = position.get("take_profit_2")
    tp1 = float(tp1) if tp1 not in (None, "NONE") else None
    tp2 = float(tp2) if tp2 not in (None, "NONE") else None

    if side == "LONG":
        if price <= stop:
            return "STOP_LOSS"
        if tp2 is not None and price >= tp2:
            return "TAKE_PROFIT_2"
        if tp1 is not None and price >= tp1:
            return "TAKE_PROFIT_1"
    else:
        if price >= stop:
            return "STOP_LOSS"
        if tp2 is not None and price <= tp2:
            return "TAKE_PROFIT_2"
        if tp1 is not None and price <= tp1:
            return "TAKE_PROFIT_1"
    return None

def check_once():
    status = run_json(["python", str(BASE / "paper_execution.py"), "status"])
    if status.get("_status") == "FAILED":
        return {"status": "FAILED", "stage": "paper_status", "detail": status}

    results = []
    for pos in list(status.get("open_positions", [])):
        asset = pos["asset"]
        price, market = get_spot_price(asset)
        if price is None:
            results.append({
                "asset": asset,
                "position_id": pos["id"],
                "status": "SKIPPED",
                "reason": "PRICE_UNAVAILABLE"
            })
            continue

        reason = should_close(pos, price)
        if reason:
            close = run_json([
                "python", str(BASE / "paper_execution.py"), "close",
                pos["id"], str(price), reason
            ])
            event = {
                "event": "POSITION_CLOSED",
                "timestamp_utc": now_utc(),
                "asset": asset,
                "position_id": pos["id"],
                "close_reason": reason,
                "market_price": price,
                "result": close,
            }
            append_journal(event)
            results.append(event)
        else:
            results.append({
                "event": "POSITION_HELD",
                "timestamp_utc": now_utc(),
                "asset": asset,
                "position_id": pos["id"],
                "market_price": price,
            })

    return {"status": "OK", "checked": len(results), "results": results}

def main():
    cmd = (Path(__file__).name, )
    if len(__import__("sys").argv) > 1 and __import__("sys").argv[1] == "watch":
        interval = int(__import__("sys").argv[2]) if len(__import__("sys").argv) > 2 else 15
        while True:
            print(json.dumps(check_once(), ensure_ascii=False, separators=(",", ":")), flush=True)
            time.sleep(interval)
    else:
        print(json.dumps(check_once(), ensure_ascii=False, separators=(",", ":")))

if __name__ == "__main__":
    main()

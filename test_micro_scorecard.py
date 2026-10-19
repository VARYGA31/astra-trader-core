#!/usr/bin/env python3
import json, tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
import micro_scorecard

def _write(path,n,wins):
    rows=[]
    base=datetime(2026,1,1,tzinfo=timezone.utc)
    # Spread losses through the sample so drawdown cannot be hidden by ordering.
    loss_slots=set()
    if n-wins:
        step=n/(n-wins)
        loss_slots={min(n-1,int(i*step)) for i in range(n-wins)}
        while len(loss_slots)<n-wins:
            loss_slots.add(len(loss_slots))
    for i in range(n):
        win=i not in loss_slots
        pnl=0.50 if win else -1.0
        row={
            "event":"OKX_POSITION_CLOSED","strategy_mode":"MICRO",
            "timestamp_utc":(base+timedelta(minutes=i)).isoformat(),
            "close_event_id":f"c{i}","order_id":f"o{i}",
            "asset":"BTC" if i%2==0 else "ETH",
            "entry":100.0,"stop_loss":99.0,"notional_usd":100.0,
            "pnl_usd":pnl,"reason":"TAKE_PROFIT_1" if win else "STOP_LOSS",
        }
        rows.append(json.dumps(row))
    path.write_text("\n".join(rows)+"\n",encoding="utf-8")

def test_micro100_pass():
    old=micro_scorecard.JOURNAL
    try:
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"journal.jsonl"; _write(p,100,80); micro_scorecard.JOURNAL=p
            s=micro_scorecard.summary()
            assert s["status"]=="MICRO_100_PASSED",s
            assert s["last_100"]["win_rate_pct"]==80.0,s
            assert s["criteria_100"]["win_rate"] is True,s
            assert s["criteria_100"]["profit_factor"] is True,s
            assert s["criteria_100"]["expectancy_r"] is True,s
    finally: micro_scorecard.JOURNAL=old

def test_micro100_rejects_79_percent():
    old=micro_scorecard.JOURNAL
    try:
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"journal.jsonl"; _write(p,100,79); micro_scorecard.JOURNAL=p
            s=micro_scorecard.summary()
            assert s["status"]=="NEEDS_TUNING",s
            assert s["criteria_100"]["win_rate"] is False,s
    finally: micro_scorecard.JOURNAL=old

def test_micro300_validation():
    old=micro_scorecard.JOURNAL
    try:
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"journal.jsonl"; _write(p,300,240); micro_scorecard.JOURNAL=p
            s=micro_scorecard.summary()
            assert s["status"]=="VALIDATED",s
            assert s["last_300"]["win_rate_pct"]==80.0,s
    finally: micro_scorecard.JOURNAL=old

if __name__=="__main__":
    test_micro100_pass();test_micro100_rejects_79_percent();test_micro300_validation()
    print({"status":"OK","micro100":"PASS"})

#!/usr/bin/env python3
"""READ-ONLY / pure-function smoke test. Places no orders and writes no production state."""
import json
import observability

events=[
    {
        "event":"OKX_POSITION_CLOSED","asset":"BTC","side":"LONG","setup_type":"PULLBACK_CONTINUATION",
        "entry":100.0,"stop_loss":98.0,"notional_usd":500.0,"pnl_usd":15.0,
        "timestamp_utc":"2026-10-12T00:00:00+00:00","close_event_id":"1"
    },
    {
        "event":"OKX_POSITION_CLOSED","asset":"BTC","side":"LONG","setup_type":"PULLBACK_CONTINUATION",
        "entry":100.0,"stop_loss":98.0,"notional_usd":500.0,"pnl_usd":-10.0,
        "timestamp_utc":"2026-10-12T01:00:00+00:00","close_event_id":"2"
    },
    {
        "event":"OKX_POSITION_CLOSED","asset":"BTC","side":"LONG","setup_type":"PULLBACK_CONTINUATION",
        "entry":100.0,"stop_loss":98.0,"notional_usd":500.0,"pnl_usd":-10.0,
        "timestamp_utc":"2026-10-12T01:00:00+00:00","close_event_id":"2"
    },
]

dedup=observability._dedupe_closes(events)
metrics=observability._metrics(dedup)

assert len(dedup)==2, dedup
assert metrics["trades"]==2, metrics
assert metrics["wins"]==1 and metrics["losses"]==1, metrics
assert metrics["profit_factor"]==1.5, metrics
assert metrics["avg_r"]==0.25, metrics

print(json.dumps({
    "status":"OK",
    "will_open_order":False,
    "will_close_order":False,
    "will_call_model":False,
    "dedupe_test":"OK",
    "metrics_test":"OK",
    "sample_metrics":metrics,
},ensure_ascii=False,indent=2))

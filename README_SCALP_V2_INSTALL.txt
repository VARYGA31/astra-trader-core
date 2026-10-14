ASTRA SCALP v2 — PRIME + FAST + TELEGRAM FUNNEL

WHY
SCALP v1 was still too selective. This patch does not simply remove safety filters.
It adds a second, lower-risk setup tier and persistent diagnostics so Telegram can
show exactly where setups are being rejected.

SCALP PRIME (original strict path)
1H regime -> 15M setup -> 5M trigger >= 4/5
quality >= 70
confidence >= 82
risk 0.35% / 0.50% / 0.75%
leverage 3x / 5x / 7x
TP1 >= 1.0R, TP2 >= 1.6R

SCALP FAST (new)
1H regime confirmed
15M setup confirmed
5M trigger >= 3/5
1H score >= 3
15M score >= 3
explicit 5M volume ratio >= 0.90
spread <= 0.06%
quality >= 64
Astra confidence >= 86
risk 0.25%, up to 0.35% on stronger FAST setups
leverage max 3x
TP1 >= 1.0R, TP2 >= 1.5R

UNCHANGED SAFETY
- news guards
- anti-chase
- max positions / exposure
- stop required
- exchange-side TP/SL
- FOK entry quality
- post-fill R:R audit
- emergency exits
- NORMAL strategy is not loosened

NEW TELEGRAM COMMAND
/scalp_stats
or button: 📈 SCALP STATS

It reports the last 6h funnel:
- checks
- PRIME / FAST gate passes
- model calls / waits / LONG+SHORT decisions
- opened trades
- FOK no-fill
- blockers: 1H, 15M, 5M, volume, spread, volatility, microstructure, chase, guards

NO NEW RAILWAY VARIABLES ARE REQUIRED.
Defaults are embedded. Optional overrides exist under SCALP_FAST_* and SCALP_STATS_*.

SAFE INSTALL
1) AUTO_DECISION=false
2) Replace all files from this ZIP.
3) Temporary Start Command:
   python repo_selfcheck.py && python test_scalp_mode.py && python test_scalp_v2.py && python test_scalp_stats.py && python test_telegram_mode_control.py && python worker.py
4) Redeploy.
5) Expected all tests status=OK and:
   will_open_order=false
   will_close_order=false
   will_call_model=false
   PRIME passed
   FAST passed
   stats_test=OK
6) Check /health: status=ok, last_error=null.
7) Restore Start Command:
   python worker.py
8) Set AUTO_DECISION=true and Redeploy.
9) In Telegram select ⚡ SCALP and use /scalp_stats after 1-3 hours.

IMPORTANT
The goal is not a fixed number of trades per day. FAST should increase opportunity
flow, while /scalp_stats tells us whether the remaining bottleneck is the market gate,
Astra WAIT, Risk Engine, or FOK execution.

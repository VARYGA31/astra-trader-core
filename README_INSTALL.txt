ASTRA MTF TRANSITION PATCH

WHY
Analytics after 312 decisions showed 283 MTF_NOT_ALIGNED skips, 12 model calls,
12 ASTRA WAITs, and 0 opened trades. The bottleneck is before Risk Engine.
This patch does NOT simply lower the normal quality threshold.

WHAT CHANGES
- NORMAL mode remains unchanged.
- New TRANSITION mode for BTC / ETH / GRAM only.
- XAU remains strict and cannot use transition mode.

TRANSITION REQUIREMENTS
- 4H trend must be MIXED, never clearly opposite.
- 4H structure/momentum cannot be explicitly opposite.
- At least one 4H component must support the direction.
- 1H setup must already be confirmed.
- 15M trigger must be strong: at least 4 components.
- MTF quality >= 60.
- Existing anti-chase must pass.
- ASTRA confidence >= 90.
- TP1 >= 1.2R and TP2 >= 2.0R.
- Transition risk budget is only 0.30% of equity by default.
- Existing daily-loss, drawdown, exposure, correlation, cooldown, news, SL/TP,
  breakeven and portfolio guards remain unchanged.

SAFE VARIABLES
MTF_TRANSITION_ENABLED=true
MTF_TRANSITION_MIN_QUALITY=60
MTF_TRANSITION_TRIGGER_MIN_COMPONENTS=4
MTF_TRANSITION_MIN_CONFIDENCE=90
MTF_TRANSITION_RISK_PCT=0.0030
MTF_TRANSITION_MIN_TP1_R=1.20
MTF_TRANSITION_MIN_TP2_R=2.00

INSTALL
1) Set AUTO_DECISION=false.
2) Upload/replace every file from this ZIP.
3) Temporary Railway Start Command:
   python repo_selfcheck.py && python test_transition_mode.py && python worker.py
4) Redeploy.
5) Expected:
   repo_selfcheck -> status OK
   test_transition_mode -> status OK
   will_open_order -> false
   will_close_order -> false
   will_call_model -> false
   transition_gate.mode -> TRANSITION
   opposite_4h_blocked -> true
   xau_transition_disabled -> true
6) Return Start Command to: python worker.py
7) Open /health, confirm status=ok and last_error=null.
8) Then set AUTO_DECISION=true.

OBSERVABILITY
Existing /analytics is preserved. New decision rows include mtf_mode=TRANSITION or NORMAL.
This lets us compare the new mode separately instead of guessing.

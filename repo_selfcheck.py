ASTRA FINAL DECISION CALIBRATION PATCH

WHY
Recent analytics showed that almost every setup reaching ASTRA ended in WAIT,
including valid NORMAL setups with strong MTF quality and confirmed triggers.
This patch changes only the FINAL MODEL DECISION POLICY + diagnostics.

WHAT DOES NOT CHANGE
- 4H -> 1H -> 15M deterministic MTF rules
- NORMAL / TRANSITION thresholds
- anti-chase
- news guards
- risk sizing / leverage
- FOK execution-quality protection
- TP / SL / breakeven
- emergency exits

NEW NORMAL POLICY
When Python has already passed a NORMAL setup, ASTRA should not ask for another
generic confirmation. If confidence is above the supplied normal minimum and no
concrete hard invalidator exists, ASTRA should choose the MTF allowed direction.

A NORMAL WAIT must be tied to a concrete category:
CHASE_RISK
STRUCTURE_CONFLICT
NEWS_RISK
VOLATILITY_RISK
RR_OR_STOP_INVALID
REVERSAL_RISK
DATA_QUALITY
XAU_MACRO_RISK

TRANSITION stays conservative. TRANSITION_WEAK remains a valid WAIT reason.

IMPORTANT SAFETY
This patch does NOT automatically convert a model WAIT into LONG/SHORT.
If the model still returns WAIT, Python honors WAIT. The prompt is calibrated,
not bypassed.

NEW DIAGNOSTICS
/health and /analytics now expose model_wait_categories / wait hardness.
recent_shadow_setups also stores:
- model_wait_category
- model_wait_is_hard_blocker
- model_wait_reason
- decision_policy_version

INSTALL
1) Set AUTO_DECISION=false.
2) Upload/replace all files from this ZIP.
3) No new Railway variables are required.
4) Temporary Start Command:
   python repo_selfcheck.py && python test_final_decision_calibration.py && python worker.py
5) Redeploy.
6) Expected test output:
   status: OK
   will_open_order: false
   will_close_order: false
   will_call_model: false
   policy_version: normal_cal_v1
   normal_wait_is_exception: true
   transition_stays_strict: true
   soft_wait_never_auto_converted: true
7) Check /health: status=ok, last_error=null.
8) Return Start Command:
   python worker.py
9) Set AUTO_DECISION=true and Redeploy.

AFTER 12-24 HOURS
Check /analytics. We want to see whether NORMAL model_waits decrease and which
hard wait categories remain. Do not lower MTF/risk thresholds until we have that data.

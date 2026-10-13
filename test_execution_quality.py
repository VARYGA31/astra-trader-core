#!/usr/bin/env python3
"""
Pure execution-quality test.
NO exchange credentials required.
NO orders are opened/closed.
"""
import json
import execution_quality

# 1) Reproduce the kind of bad GRAM fill seen in the journal:
#    planned setup looked good near 1.376, but a SHORT around 1.37019 makes
#    the original TP1/TP2 reward/risk unacceptable.
bad=execution_quality.audit_price(
    "SHORT",1.3701918620689657,1.387,1.358,1.341,1.2,2.0
)
assert bad["passed"] is False, bad

# 2) A good pre-order reference should pass and produce a FOK boundary that
#    guarantees both slippage and R:R constraints.
guard=execution_quality.build_entry_guard(
    "GRAM","SHORT",1.376,1.387,1.358,1.341,"NORMAL"
)
assert guard["passed"] is True, guard
limit=guard["raw_fok_limit_price"]

# Any SHORT fill at/above the derived floor must preserve configured R:R.
at_limit=execution_quality.audit_fill(
    "GRAM","SHORT",1.376,limit,1.387,1.358,1.341,"NORMAL"
)
assert at_limit["passed"] is True, at_limit

# 3) Deliberately worse fill must fail.
worse=execution_quality.audit_fill(
    "GRAM","SHORT",1.376,1.3701918620689657,1.387,1.358,1.341,"NORMAL"
)
assert worse["passed"] is False, worse

print(json.dumps({
    "status":"OK",
    "will_open_order":False,
    "will_close_order":False,
    "will_call_model":False,
    "bad_fill_rejected":not bad["passed"],
    "good_reference_passed":guard["passed"],
    "derived_fok_limit":limit,
    "limit_fill_passed":at_limit["passed"],
    "worse_fill_rejected":not worse["passed"],
    "bad_fill_tp1_r":bad.get("tp1_r"),
    "bad_fill_tp2_r":bad.get("tp2_r"),
},ensure_ascii=False,indent=2))

#!/usr/bin/env python3
"""Pure no-exchange regression: adverse stop fills must not report status OK."""
import execution_audit


def trade(side, entry, stop, close, asset="XAU"):
    return {"asset":asset,"side":side,"entry":entry,"stop_loss":stop,
            "exit_price":close,"timestamp_utc":"2026-10-29T16:17:27Z",
            "reason":"STOP_LOSS","pnl_usd":-7.97}


def test_adverse_stop_reports_review_and_r():
    bad=trade("SHORT",4034.9,4049.0,4053.4)
    summary=execution_audit.stop_exit_audit([bad])
    assert summary["status"]=="NEEDS_EXECUTION_REVIEW",summary
    assert summary["beyond_stop_count"]==1,summary
    assert summary["worst_adverse_beyond_stop_r"]==round(4.4/14.1,4),summary
    assert summary["review_requires"]=="OKX_ALGO_AND_FILL_HISTORY",summary
    assert summary["order_capability"] is False,summary


def test_favourable_or_exact_stop_not_flagged():
    for side,entry,stop,close in [
        ("SHORT",4034.9,4049.0,4049.0),
        ("SHORT",4034.9,4049.0,4043.0),
        ("LONG",4034.9,4020.0,4021.0),
    ]:
        report=execution_audit.stop_exit_audit([trade(side,entry,stop,close)])
        assert report["beyond_stop_count"]==0,report
        assert report["status"]=="NO_ADVERSE_STOP_CLOSES",report


def test_long_side_adverse_stop_detected():
    result=execution_audit.stop_exit_audit([trade("LONG",100,95,93)])
    assert result["status"]=="NEEDS_EXECUTION_REVIEW",result
    assert result["worst_adverse_beyond_stop_r"]==0.4,result


def test_empty_does_not_claim_exchange_verification():
    result=execution_audit.stop_exit_audit([])
    assert result["closed_sample"]==0 and result["status"]=="NO_ADVERSE_STOP_CLOSES",result
    assert result["order_capability"] is False,result


if __name__=="__main__":
    test_adverse_stop_reports_review_and_r()
    test_favourable_or_exact_stop_not_flagged()
    test_long_side_adverse_stop_detected()
    test_empty_does_not_claim_exchange_verification()
    print("STOP_OVERRUN_HONEST_STATUS=PASS")

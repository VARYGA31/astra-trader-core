#!/usr/bin/env python3
"""No-network XAU/ETH/BTC incident evidence regression; NO order authority."""
import trade_incident_review as incident


def close(**kw):
    row={
        "close_event_id":"XAU:xau-entry-123",
        "asset":"XAU","side":"SHORT",
        "entry":4034.9,"stop_loss":4049.0,"exit_price":4053.4,
        "notional_usd":1444.49,"pnl_usd":-7.972408737,
        "gross_pnl_usd":-7.4,"fee_usd":-0.5,"funding_fee_usd":-0.07,
        "reason":"STOP_LOSS","setup_type":"TREND_CONTINUATION",
        "volatility_regime":"NORMAL","confidence":92,
        "opened_at_utc":"2026-10-29T15:01:00Z",
        "timestamp_utc":"2026-10-29T16:17:27Z",
    }
    row.update(kw)
    return row


def test_gold_stop_observation_does_not_claim_cause_or_block_asset():
    result=incident.review_trade(close())
    assert result["severity"]=="EXECUTION_REVIEW",result
    assert result["price_evidence"]["adverse_price_beyond_stop_r"]==round(4.4/14.1,4),result
    assert result["price_evidence"]["net_realized_r_approx"] is not None,result
    assert result["cause"]=="UNDETERMINED",result
    assert result["close_reason_verified_by_exchange"] is False,result
    assert result["may_blacklist_asset"] is False,result
    assert "CLOSE_FILLS_AND_PARTIAL_FILLS_WITH_TIMESTAMPS" in result["next_evidence_checks"],result
    assert result["cost_evidence"]["gross_minus_net_usd"]>0,result
    assert result["duration_minutes"]==76.45,result


def test_favourable_stop_or_win_not_overshoot():
    result=incident.review_trade(close(exit_price=4045,reason="STOP_LOSS"))
    assert result["severity"]=="SETUP_REVIEW",result
    assert result["price_evidence"]["adverse_price_beyond_stop_r"]==0.0,result
    winner=incident.review_trade(close(pnl_usd=8.0,exit_price=4000,reason="TAKE_PROFIT_1"))
    assert winner["severity"]=="OBSERVE",winner
    assert not winner["next_evidence_checks"],winner


def test_bad_geometry_does_not_fabricate_r():
    result=incident.review_trade(close(entry=0,stop_loss=10,exit_price=15,notional_usd=None))
    assert result["price_evidence"]["planned_risk_usd_approx"] is None,result
    assert result["price_evidence"]["adverse_price_beyond_stop_r"] is None,result
    assert "RISK_GEOMETRY_UNVERIFIED" in result["tags"],result


def test_partial_take_profit_not_claimed_exact_cost():
    result=incident.review_trade(close(tp1_taken=True))
    assert "PARTIAL_EXIT_PATH_NEEDS_FILLS" in result["tags"],result
    assert "indicative" in result["price_evidence"]["notional_basis_note"],result


def test_deterministic_summary_and_one_loss_no_blacklist():
    data=[close(),close(close_event_id="ETH:x",asset="ETH",side="LONG",
                      entry=100,stop_loss=95,exit_price=95.2,pnl_usd=-1.3)]
    summary=incident.summarize(data,limit=2)
    assert summary["losing_trades"]==2,summary
    assert summary["exit_price_beyond_planned_stop"]==1,summary
    assert summary["automatic_strategy_or_asset_changes"] is False,summary
    assert all(x["may_blacklist_asset"] is False for x in summary["recent_incidents"]),summary
    assert incident.review_trade(data[0])["incident_id"]==incident.review_trade(data[0])["incident_id"]


if __name__=="__main__":
    test_gold_stop_observation_does_not_claim_cause_or_block_asset()
    test_favourable_stop_or_win_not_overshoot()
    test_bad_geometry_does_not_fabricate_r()
    test_partial_take_profit_not_claimed_exact_cost()
    test_deterministic_summary_and_one_loss_no_blacklist()
    print("INCIDENT_EVIDENCE=PASS; orders=0; asset_blacklists=0")

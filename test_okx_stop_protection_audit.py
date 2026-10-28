#!/usr/bin/env python3
"""No API keys, no orders, no network: pure OKX stop coverage tests."""
import okx_stop_protection_audit as a


def exchange(qty=2.0):
    return {"details":[{"asset":"BTC","instId":"BTC-USDT-SWAP","side":"LONG",
                        "qty_contracts":qty}],"open_positions":1}


def algo(qty, price=95, side="sell", aid="id1"):
    return {"instId":"BTC-USDT-SWAP","algoId":aid,"ordType":"conditional",
            "slTriggerPx":str(price),"sz":str(qty),"side":side}


def pending(items):
    return {"conditional":items,"oco":[]}


def test_complete_and_partial_coverage():
    p=a.analyze(exchange(),{"BTC":{"stop_loss":95}},pending([algo(1,aid="1"),algo(1,aid="2")]))
    assert p["status"]=="OK" and p["verified_positions"]==1,p
    partial=a.analyze(exchange(),{},pending([algo(1)]))
    assert partial["status"]=="ALERT" and partial["positions"][0]["status"]=="PARTIAL_STOP_COVERAGE",partial
    absent=a.analyze(exchange(),{},pending([]))
    assert absent["status"]=="ALERT" and absent["positions"][0]["status"]=="MISSING_STOP_ALGO",absent


def test_incomplete_or_unknown_size_is_not_verified():
    unknown=a.analyze(exchange(),{},pending([]),complete=False)
    assert unknown["status"]=="UNKNOWN" and unknown["reason"]=="PENDING_LIST_INCOMPLETE",unknown
    row=algo(2);row.pop("sz")
    unknown2=a.analyze(exchange(),{},pending([row]))
    assert unknown2["status"]=="UNKNOWN" and unknown2["unknown_count"]==1,unknown2
    missing_kind=a.analyze(exchange(),{},{"oco":[]})
    assert missing_kind["status"]=="UNKNOWN",missing_kind


def test_wrong_direction_and_worse_stop_flag():
    wrong=a.analyze(exchange(),{},pending([algo(2,side="buy")]))
    assert wrong["positions"][0]["status"]=="MISSING_STOP_ALGO",wrong
    worse=a.analyze(exchange(),{"BTC":{"stop_loss":95}},pending([algo(2,price=90)]))
    assert worse["positions"][0]["status"]=="STOP_WORSE_THAN_PLAN",worse
    better=a.analyze(exchange(),{"BTC":{"stop_loss":95}},pending([algo(2,price=97)]))
    assert better["positions"][0]["status"]=="VERIFIED_ACTIVE_STOP",better


def test_no_position_is_not_flagged_as_missing():
    x=a.analyze({"details":[],"open_positions":0},{},pending([]))
    assert x["status"]=="NO_OPEN_POSITIONS",x


if __name__=="__main__":
    test_complete_and_partial_coverage()
    test_incomplete_or_unknown_size_is_not_verified()
    test_wrong_direction_and_worse_stop_flag()
    test_no_position_is_not_flagged_as_missing()
    print("READ_ONLY_STOP_COVERAGE=PASS; orders=0")

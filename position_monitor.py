#!/usr/bin/env python3
import json
import market_snapshot,paper_execution,cooldown,trade_journal,config
def check_once():
    s=paper_execution.status();out=[]
    for p in list(s.get("open_positions",[])):
        m=market_snapshot.snapshot(p["asset"]);px=m.get("spot",{}).get("price")
        if px is None:out.append({"status":"SKIPPED","reason":"PRICE_UNAVAILABLE","asset":p["asset"]});continue
        px=float(px);side=p["side"];stop=float(p["stop_loss"]);tp1=p.get("take_profit_1");tp2=p.get("take_profit_2")
        tp1=float(tp1) if tp1 is not None else None;tp2=float(tp2) if tp2 is not None else None
        reason=None;frac=None
        if side=="LONG":
            if px<=stop:reason,frac="STOP_LOSS",1
            elif tp2 is not None and px>=tp2:reason,frac="TAKE_PROFIT_2",1
            elif tp1 is not None and not p.get("tp1_taken") and px>=tp1:reason,frac="TAKE_PROFIT_1",.5
        else:
            if px>=stop:reason,frac="STOP_LOSS",1
            elif tp2 is not None and px<=tp2:reason,frac="TAKE_PROFIT_2",1
            elif tp1 is not None and not p.get("tp1_taken") and px<=tp1:reason,frac="TAKE_PROFIT_1",.5
        if reason:
            r=paper_execution.partial_close(p["id"],px,frac,reason)
            trade_journal.append_event({"event":"POSITION_EXIT","asset":p["asset"],"position_id":p["id"],"reason":reason,"price":px,"result":r})
            if reason in {"STOP_LOSS","TAKE_PROFIT_2"}:cooldown.set_cooldown(p["asset"],reason=reason)
            out.append(r)
        else:out.append({"status":"HELD","asset":p["asset"],"position_id":p["id"],"price":px})
    return {"status":"OK","results":out}
if __name__=="__main__":print(json.dumps(check_once(),ensure_ascii=False))

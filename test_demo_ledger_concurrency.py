#!/usr/bin/env python3
import tempfile
import threading
from pathlib import Path

import demo_ledger

def test_concurrent_closed_trade_updates():
    old=demo_ledger.FILE
    try:
        with tempfile.TemporaryDirectory() as td:
            demo_ledger.FILE=Path(td)/"demo_ledger.json"
            workers=[]
            errors=[]
            def run():
                try:
                    demo_ledger.apply_closed_trade(1.0)
                except Exception as e:
                    errors.append(e)
            for _ in range(50):
                t=threading.Thread(target=run)
                workers.append(t)
                t.start()
            for t in workers:
                t.join()
            assert not errors,errors
            s=demo_ledger.load()
            assert int(s["closed_trades"])==50,s
            assert abs(float(s["realized_pnl"])-50.0)<1e-9,s
            leftovers=list(Path(td).glob("*.tmp"))
            assert leftovers==[],leftovers
    finally:
        demo_ledger.FILE=old

if __name__=="__main__":
    test_concurrent_closed_trade_updates()
    print({"status":"OK","demo_ledger":"CONCURRENCY_SAFE"})

#!/usr/bin/env python3
"""Offline demo-only operator acknowledgement: balance transfer != trade PnL."""
import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import config
import daily_loss_latch
import equity_guard


def ledger(realized_today=0, equity=4808.85):
    return {"equity":equity,"initial_equity":5000.0,
            "daily_pnl":realized_today}


def time_today():
    return datetime.now(timezone.utc).date().isoformat()


def test_operator_ack_and_new_loss_relocks_once():
    day=time_today()
    with tempfile.TemporaryDirectory() as t, \
         patch.object(equity_guard,"BASELINE",Path(t)/"baseline.json"), \
         patch.object(daily_loss_latch,"FILE",Path(t)/"latch.json"), \
         patch.object(config,"EXECUTION_MODE","okx_demo"), \
         patch.object(config,"OKX_DEMO_BALANCE_CHANGE_ACK_DATE_UTC",day), \
         patch.object(config,"DAILY_LOSS_LIMIT_PCT",0.003):
        equity_guard._cached=None
        equity_guard._cached_until=0
        # Real prior daily latch: do not silently clear without confirmed-flat
        # exchange context, even after PnL recovers.
        pre=daily_loss_latch.observe(5000,-1199)
        assert pre["latched"]
        r1=equity_guard.snapshot(ledger(),provider=lambda:{"data":[{"totalEq":"6008.29"}]},exchange_flat=True)
        assert r1["verified"] and r1["daily_pnl"]==0,r1
        assert r1["operator_demo_balance_ack_date_utc"] is None,r1
        # Now the broker reports 4808.84666, with NO OPEN POSITIONS. The
        # difference is user-acknowledged, not asserted exchange-verified.
        r2=equity_guard.snapshot(ledger(),provider=lambda:{"data":[{"totalEq":"4808.84666"}]},exchange_flat=True)
        assert r2["verified"] and abs(r2["account_daily_change"]+1199.44334)<0.001,r2
        assert abs(r2["daily_pnl"])<1e-5,r2
        assert r2["operator_demo_balance_ack_date_utc"]==day,r2
        first=daily_loss_latch.observe(5000,r2["daily_pnl"],operator_demo_balance_ack_date_utc=day)
        assert first["latched"] is False,first
        assert json.loads(daily_loss_latch.FILE.read_text())["operator_demo_balance_ack_date_utc"]==day
        # The original ledger PnL persists. A NEW -16 USD closed trade must
        # exceed the actual -15 USD daily loss cap and be latched forever today.
        r3=equity_guard.snapshot(ledger(-16,4792.85),provider=lambda:{"data":[{"totalEq":"4792.84666"}]},exchange_flat=True)
        assert r3["daily_pnl"]<=-16,r3
        breached=daily_loss_latch.observe(5000,r3["daily_pnl"],operator_demo_balance_ack_date_utc=day)
        assert breached["latched"] is True,breached
        r4=equity_guard.snapshot(ledger(0,4808.85),provider=lambda:{"data":[{"totalEq":"4808.84666"}]},exchange_flat=False)
        still=daily_loss_latch.observe(5000,r4["daily_pnl"],operator_demo_balance_ack_date_utc=day)
        assert still["latched"] is True,still


def test_no_auto_ack_without_flat_or_without_explicit_date():
    day=time_today()
    for ack,flat in [(day,False),("",True),("2020-01-01",True)]:
        with tempfile.TemporaryDirectory() as t, \
             patch.object(equity_guard,"BASELINE",Path(t)/"baseline.json"), \
             patch.object(config,"EXECUTION_MODE","okx_demo"), \
             patch.object(config,"OKX_DEMO_BALANCE_CHANGE_ACK_DATE_UTC",ack):
            equity_guard._cached=None
            equity_guard._cached_until=0
            equity_guard.snapshot(ledger(),provider=lambda:{"data":[{"totalEq":"6008.29"}]},exchange_flat=flat)
            result=equity_guard.snapshot(ledger(),provider=lambda:{"data":[{"totalEq":"4808.84666"}]},exchange_flat=flat)
            assert result["daily_pnl"] < -1100,(ack,flat,result)
            assert result["operator_demo_balance_ack_date_utc"] is None,result


def test_no_rebase_below_exchange_ledger_equity_or_after_real_loss():
    day=time_today()
    for l,balance in [(ledger(),4000.0),(ledger(-18),4808.85)]:
        with tempfile.TemporaryDirectory() as t, \
             patch.object(equity_guard,"BASELINE",Path(t)/"baseline.json"), \
             patch.object(config,"EXECUTION_MODE","okx_demo"), \
             patch.object(config,"OKX_DEMO_BALANCE_CHANGE_ACK_DATE_UTC",day), \
             patch.object(config,"DAILY_LOSS_LIMIT_PCT",0.003):
            equity_guard._cached=None
            equity_guard._cached_until=0
            equity_guard.snapshot(l,provider=lambda:{"data":[{"totalEq":"6008.29"}]},exchange_flat=True)
            result=equity_guard.snapshot(l,provider=lambda x=balance:{"data":[{"totalEq":str(x)}]},exchange_flat=True)
            assert result["operator_demo_balance_ack_date_utc"] is None,result


def test_ack_does_not_automatically_clear_real_loss_even_if_present():
    day=time_today()
    with tempfile.TemporaryDirectory() as t, \
         patch.object(daily_loss_latch,"FILE",Path(t)/"latch.json"), \
         patch.object(config,"EXECUTION_MODE","okx_demo"), \
         patch.object(config,"DAILY_LOSS_LIMIT_PCT",0.003):
        daily_loss_latch.observe(5000,-20)
        result=daily_loss_latch.observe(5000,-16,operator_demo_balance_ack_date_utc=day)
        assert result["latched"] and result["reason"]=="DAILY_LOSS_LIMIT_REACHED",result


if __name__=="__main__":
    test_operator_ack_and_new_loss_relocks_once()
    test_no_auto_ack_without_flat_or_without_explicit_date()
    test_no_rebase_below_exchange_ledger_equity_or_after_real_loss()
    test_ack_does_not_automatically_clear_real_loss_even_if_present()
    print("DEMO_BALANCE_ACK_SAFETY=PASS; real_losses_still_guarded=true")

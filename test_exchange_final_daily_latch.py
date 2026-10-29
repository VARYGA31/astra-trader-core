#!/usr/bin/env python3
"""No-network regression: exchange FINAL pre-order guard cannot lose daily latch."""
import tempfile
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch,MagicMock

import config
import daily_loss_latch
import execution_router


def test_final_preorder_latch_survives_pnl_recovery():
    today=datetime.now(timezone.utc).date().isoformat()
    with tempfile.TemporaryDirectory() as folder, \
         patch.object(daily_loss_latch,"FILE",Path(folder)/"daily.json"), \
         patch.object(config,"DAILY_LOSS_LIMIT_PCT",0.06), \
         patch.object(config,"EXECUTION_MODE","okx_demo"), \
         patch.object(config,"ONE_POSITION_PER_ASSET",True), \
         patch.object(config,"BLOCK_BTC_ETH_SAME_DIRECTION",True), \
         patch.object(execution_router,"demo_ledger") as ledger, \
         patch.object(execution_router,"equity_guard") as equity, \
         patch.object(execution_router,"OKXDemoAdapter") as adapter_class:
        adapter=adapter_class.return_value
        adapter.account_tradability.return_value={"available":True}
        adapter.exchange_active_summary.return_value={
            "assets":[],"details":[],"open_positions":0,
            "current_exposure_usd":0,"unrealized_pnl_usd":0,
        }
        ledger.status.return_value={
            "initial_equity":100.0,"equity":100.0,
            "daily_pnl":-6.1,"trading_halted":False,
        }
        # First order attempt crosses the daily loss threshold.
        equity.snapshot.return_value={
            "verified":True,"equity":93.9,"daily_pnl":-6.1
        }
        proposal={"asset":"BTC","action":"LONG","strategy_mode":"NORMAL"}
        sizing={"position_notional_usd":10,"leverage":2,
                "stop_loss":95,"take_profit_1":110,"take_profit_2":120}
        first=execution_router.open_trade(proposal,sizing)
        assert first["status"]=="REJECTED",first
        assert first["reason"]=="DAILY_LOSS_EXCHANGE_GUARD",first
        assert first["daily_loss_latch"]["latched"] is True,first
        # Current balance subsequently recovers, but the recorded breach
        # must still block submission for the same UTC calendar day.
        equity.snapshot.return_value={
            "verified":True,"equity":101.0,"daily_pnl":1.0
        }
        second=execution_router.open_trade(proposal,sizing)
        assert second["status"]=="REJECTED",second
        assert second["reason"]=="DAILY_LOSS_EXCHANGE_GUARD",second
        assert second["daily_loss_latch"]["latched"] is True,second
        assert second["daily_loss_latch"]["date_utc"]==today,second
        assert adapter.open_fok.call_count==0
        assert adapter.set_leverage.call_count==0
        assert adapter.private_post.call_count==0


def test_exchange_final_fails_closed_on_corrupt_latch():
    with tempfile.TemporaryDirectory() as folder, \
         patch.object(daily_loss_latch,"FILE",Path(folder)/"daily.json"), \
         patch.object(config,"EXECUTION_MODE","okx_demo"), \
         patch.object(execution_router,"demo_ledger") as ledger, \
         patch.object(execution_router,"equity_guard") as equity, \
         patch.object(execution_router,"OKXDemoAdapter") as adapter_class:
        daily_loss_latch.FILE.write_text("{bad-json",encoding="utf-8")
        adapter=adapter_class.return_value
        adapter.account_tradability.return_value={"available":True}
        adapter.exchange_active_summary.return_value={
            "assets":[],"details":[],"open_positions":0,
            "current_exposure_usd":0,"unrealized_pnl_usd":0,
        }
        ledger.status.return_value={"initial_equity":100.0,"equity":100.0,
                                    "daily_pnl":0,"trading_halted":False}
        equity.snapshot.return_value={"verified":True,"equity":100.0,"daily_pnl":0.0}
        result=execution_router.open_trade(
            {"asset":"BTC","action":"LONG","strategy_mode":"NORMAL"},
            {"position_notional_usd":10,"leverage":2,"stop_loss":95,
             "take_profit_1":110,"take_profit_2":120}
        )
        assert result["status"]=="REJECTED" and result["reason"]=="DAILY_LOSS_EXCHANGE_GUARD",result
        assert result["daily_loss_latch"]["reason"]=="LATCH_STATE_UNREADABLE",result
        adapter.open_fok.assert_not_called()


if __name__=="__main__":
    test_final_preorder_latch_survives_pnl_recovery()
    test_exchange_final_fails_closed_on_corrupt_latch()
    print("FINAL_OKX_UTC_LOSS_LATCH=PASS; exchange_orders=0")

#!/usr/bin/env python3
"""Pure Execution v4.1 FOK regression. No network and no real orders."""
import json

import config
import execution_router
import okx_demo_adapter

# executable_quote must use ask for LONG and bid for SHORT, never last.
a=object.__new__(okx_demo_adapter.OKXDemoAdapter)
a.ticker_row=lambda asset: {"last":"100.00","bidPx":"99.99","askPx":"100.01"}
ql=okx_demo_adapter.OKXDemoAdapter.executable_quote(a,"BTC","LONG")
qs=okx_demo_adapter.OKXDemoAdapter.executable_quote(a,"BTC","SHORT")
assert ql["reference"]==100.01 and ql["reference_side"]=="ASK",ql
assert qs["reference"]==99.99 and qs["reference_side"]=="BID",qs

class FakeAdapter:
    instances=[]
    def __init__(self):
        self.quote_n=0
        self.open_n=0
        FakeAdapter.instances.append(self)

    def exchange_active_summary(self):
        return {"open_positions":0,"current_exposure_usd":0.0,"assets":[],"details":[]}

    def executable_quote(self,asset,action):
        self.quote_n+=1
        if self.quote_n==1:
            return {"last":100.0,"bid":99.99,"ask":100.01,"mid":100.0,"spread_pct":0.02,
                    "reference":100.01 if action=="LONG" else 99.99,
                    "reference_side":"ASK" if action=="LONG" else "BID"}
        return {"last":100.01,"bid":100.00,"ask":100.02,"mid":100.01,"spread_pct":0.02,
                "reference":100.02 if action=="LONG" else 100.00,
                "reference_side":"ASK" if action=="LONG" else "BID"}

    def normalize_entry_limit_price(self,asset,action,price):
        return str(price)

    def open_fok(self,asset,action,notional,leverage,sl,tp1,tp2,limit,reference):
        self.open_n+=1
        if self.open_n==1:
            return {
                "filled":False,"order_id":"cancel-1","inst_id":"BTC-USDT-SWAP",
                "side":action,"requested_qty_contracts":1.0,"qty_contracts":0.0,
                "entry":None,"leverage":float(leverage),"position_value_usd_approx":0.0,
                "protection":{},"order_state":"canceled","reference_price":reference,
                "limit_price":float(limit),
            }
        return {
            "filled":True,"order_id":"fill-2","inst_id":"BTC-USDT-SWAP",
            "side":action,"requested_qty_contracts":1.0,"qty_contracts":1.0,
            "entry":100.02,"leverage":float(leverage),"position_value_usd_approx":100.02,
            "protection":{"mode":"FULL_TP2_PLUS_SL","tp1_qty_contracts":0.0,"tp2_qty_contracts":1.0},
            "order_state":"filled","reference_price":reference,"limit_price":float(limit),
        }

old_adapter=execution_router.OKXDemoAdapter
old_status=execution_router.demo_ledger.status
old_register=execution_router.okx_position_monitor.register_trade
old_append=execution_router.trade_journal.append_event
old_notify=execution_router.telegram_notifier.notify_open
old_attempts=config.OKX_ENTRY_FOK_MAX_ATTEMPTS
old_delay=config.OKX_ENTRY_FOK_RETRY_DELAY_MS
old_mode=config.EXECUTION_MODE
old_order=config.OKX_ENTRY_ORDER_TYPE
try:
    execution_router.OKXDemoAdapter=FakeAdapter
    execution_router.demo_ledger.status=lambda: {"equity":5000.0}
    execution_router.okx_position_monitor.register_trade=lambda record: {"status":"OK"}
    execution_router.trade_journal.append_event=lambda event: {"status":"OK"}
    execution_router.telegram_notifier.notify_open=lambda record: {"status":"OK"}
    config.OKX_ENTRY_FOK_MAX_ATTEMPTS=2
    config.OKX_ENTRY_FOK_RETRY_DELAY_MS=0
    config.EXECUTION_MODE="okx_demo"
    config.OKX_ENTRY_ORDER_TYPE="fok"

    decision={
        "asset":"BTC","action":"LONG","mtf_mode":"NORMAL","strategy_mode":"NORMAL",
        "adaptive_mode":True,"planned_entry":100.0,"confidence":90,
        "data_quality":"OK","volatility_regime":"NORMAL","setup_type":"TOURNAMENT_V5",
    }
    risk={
        "position_notional_usd":100.0,"leverage":2.0,
        "entry":100.0,"stop_loss":99.0,"take_profit_1":101.30,"take_profit_2":102.10,
        "tp1_r":1.3,"tp2_r":2.1,"mtf_quality":85,"trade_quality":85,
        "risk_pct_budget":0.001,
    }
    out=execution_router.open_trade(decision,risk)
    assert out["status"]=="OKX_DEMO_OPENED",out
    trade=out["trade"]
    assert trade["entry_reference_mode"]=="EXECUTABLE_TOUCH_V4_1",trade
    assert len(trade["entry_attempts"])==2,trade
    assert trade["entry_attempts"][0]["filled"] is False,trade
    assert trade["entry_attempts"][1]["filled"] is True,trade
    assert trade["pre_order_quote"]["reference_side"]=="ASK",trade
    assert abs(trade["pre_order_reference"]-100.02)<1e-12,trade
finally:
    execution_router.OKXDemoAdapter=old_adapter
    execution_router.demo_ledger.status=old_status
    execution_router.okx_position_monitor.register_trade=old_register
    execution_router.trade_journal.append_event=old_append
    execution_router.telegram_notifier.notify_open=old_notify
    config.OKX_ENTRY_FOK_MAX_ATTEMPTS=old_attempts
    config.OKX_ENTRY_FOK_RETRY_DELAY_MS=old_delay
    config.EXECUTION_MODE=old_mode
    config.OKX_ENTRY_ORDER_TYPE=old_order

print(json.dumps({
    "status":"OK",
    "will_open_real_order":False,
    "touch_reference":"OK",
    "guarded_fok_retry":"OK",
    "max_attempts":2,
},ensure_ascii=False,indent=2))

#!/usr/bin/env python3
import config
import trade_universe
import risk_engine
import decision_gate
import execution_router
from okx_demo_adapter import OKXDemoAdapter

def test_trade_universe_dynamic_defi_and_gold():
    u={
        "eligible":[
            {"asset":"UNI","spread_pct":0.02,"liquidity_score":9.0,"volume_proxy_usd":1000000},
            {"asset":"AAVE","spread_pct":0.03,"liquidity_score":8.0,"volume_proxy_usd":900000},
            {"asset":"PENDLE","spread_pct":0.04,"liquidity_score":7.0,"volume_proxy_usd":800000},
            {"asset":"CRV","spread_pct":0.11,"liquidity_score":10.0,"volume_proxy_usd":2000000},
        ]
    }
    old_top=config.NORMAL_DEFI_TOP_N
    old_gold=config.NORMAL_GOLD_TRADING_ENABLED
    old_defi=config.NORMAL_DEFI_TRADING_ENABLED
    try:
        config.NORMAL_DEFI_TOP_N=2
        config.NORMAL_GOLD_TRADING_ENABLED=True
        config.NORMAL_DEFI_TRADING_ENABLED=True
        assets=trade_universe.normal_assets(u)
        assert assets[:4]==("BTC","ETH","GRAM","XAU"),assets
        assert "UNI" in assets and "AAVE" in assets,assets
        assert "PENDLE" not in assets,assets
        assert "CRV" not in assets,assets
    finally:
        config.NORMAL_DEFI_TOP_N=old_top
        config.NORMAL_GOLD_TRADING_ENABLED=old_gold
        config.NORMAL_DEFI_TRADING_ENABLED=old_defi

def _risk_input(asset="AAVE",confidence=90,quality=88):
    return {
        "asset":asset,"action":"LONG",
        "equity":10000.0,"initial_equity":10000.0,"daily_pnl":0.0,
        "open_positions":0,"current_exposure_usd":0.0,"asset_already_open":False,
        "entry":100.0,"stop_loss":98.0,"take_profit_1":103.0,"take_profit_2":104.5,
        "confidence":confidence,"mtf_quality":quality,"mtf_mode":"NORMAL","strategy_mode":"NORMAL",
        "data_quality":"OK","critical_news_verified":True,"volatility_regime":"NORMAL",
    }

def test_defi_risk_is_stricter():
    r=risk_engine.evaluate(_risk_input())
    assert r["status"]=="APPROVED",r
    assert r["actual_risk_pct"]<=config.DEFI_TRADE_HARD_RISK_PCT+1e-12,r
    assert r["leverage"]<=config.DEFI_TRADE_MAX_LEVERAGE+1e-12,r

    low=risk_engine.evaluate(_risk_input(confidence=config.DEFI_TRADE_MIN_CONFIDENCE-1))
    assert low["status"]=="REJECTED",low

def test_defi_pretrade_guards():
    wide={
        "asset":"AAVE",
        "decision_context":{
            "market":{"perp_okx":{"bid_price":99.8,"ask_price":100.2}},
            "news":{"events":[]},
        },
    }
    g=decision_gate._defi_pretrade_guard(wide)
    assert g and g["reason"]=="DEFI_SPREAD_TOO_WIDE",g

    security={
        "asset":"AAVE",
        "decision_context":{
            "market":{"perp_okx":{"bid_price":99.99,"ask_price":100.01}},
            "news":{"events":[{
                "id":"x","source":"TEST","title":"Aave protocol exploit reported",
                "published_at_utc":"2099-01-01T00:00:00+00:00",
            }]},
        },
    }
    g=decision_gate._defi_pretrade_guard(security)
    assert g and g["reason"]=="DEFI_SECURITY_HALT",g

def test_account_tradability_probe():
    a=OKXDemoAdapter.__new__(OKXDemoAdapter)
    a.inst_id=lambda asset:"XAU-USDT-SWAP"
    a.instrument=lambda asset:{"state":"live"}
    a.account_instrument=lambda asset:None
    x=a.account_tradability("XAU")
    assert x["available"] is False and x["reason"]=="ACCOUNT_INSTRUMENT_UNAVAILABLE",x
    a.account_instrument=lambda asset:{"instId":"XAU-USDT-SWAP","state":"live","groupId":"6"}
    x=a.account_tradability("XAU")
    assert x["available"] is True,x

def test_router_defi_concentration_and_preflight():
    class FakeUnavailable:
        def account_tradability(self,asset):
            return {"available":False,"reason":"ACCOUNT_INSTRUMENT_UNAVAILABLE","instrument":"XAU-USDT-SWAP"}
    old_mode=config.EXECUTION_MODE
    old_adapter=execution_router.OKXDemoAdapter
    try:
        config.EXECUTION_MODE="okx_demo"
        execution_router.OKXDemoAdapter=lambda:FakeUnavailable()
        x=execution_router.open_trade({"asset":"XAU","action":"LONG"},{"position_notional_usd":10})
        assert x["reason"]=="OKX_ACCOUNT_INSTRUMENT_UNAVAILABLE",x

        class FakeDefi:
            def account_tradability(self,asset): return {"available":True,"reason":"OK"}
            def exchange_active_summary(self):
                return {
                    "open_positions":1,"current_exposure_usd":100.0,"assets":["AAVE"],
                    "details":[{"asset":"AAVE","side":"LONG","notional_usd":100.0}],
                }
        execution_router.OKXDemoAdapter=lambda:FakeDefi()
        x=execution_router.open_trade(
            {"asset":"UNI","action":"SHORT","mtf_mode":"NORMAL","strategy_mode":"NORMAL"},
            {"position_notional_usd":10},
        )
        assert x["reason"]=="DEFI_CONCENTRATION_EXCHANGE_GUARD",x
    finally:
        config.EXECUTION_MODE=old_mode
        execution_router.OKXDemoAdapter=old_adapter

if __name__=="__main__":
    test_trade_universe_dynamic_defi_and_gold()
    test_defi_risk_is_stricter()
    test_defi_pretrade_guards()
    test_account_tradability_probe()
    test_router_defi_concentration_and_preflight()
    print({
        "status":"OK",
        "normal_extended_markets":["XAU","DEFI_DYNAMIC_TOP_N"],
        "micro_unchanged":["BTC","ETH","GRAM"],
    })

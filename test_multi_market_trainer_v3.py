#!/usr/bin/env python3
"""Pure Multi-Market Trainer v3 regression. No network, OpenAI or orders."""
import json
import config
import adaptive_trainer
import multi_market_trainer
import telegram_control

def frame(trend="BULLISH",structure="BULLISH",momentum="BULLISH",atr_pct=0.30,vol=1.4,breakout=True):
    return {
        "status":"OK","last_confirmed_close_time_ms":1700000000000,"close":100.0,
        "changes_pct":{"1bar":0.22,"3bar":0.5,"6bar":0.8},
        "indicators":{"ema20":99.5,"ema50":99.0,"ema200":98.0,"rsi14":60.0,"atr14":0.3,"atr_pct":atr_pct},
        "regimes":{"trend":trend,"structure":structure,"momentum":momentum},
        "structure":{"breakout_up":breakout,"breakout_down":False,"prior_20_high":99.7,"prior_20_low":98.0},
        "volume":{"ratio_to_avg20":vol},
        "last_candle":{"open":99.7,"high":100.2,"low":99.6,"close":100.0},
    }

def package(asset="AAVE",gold=False):
    frames={
        "5m":frame(atr_pct=0.25),
        "15m":frame(atr_pct=0.35),
        "1h":frame(atr_pct=0.65),
        "4h":frame(atr_pct=1.0),
    }
    market={
        "data_quality":{"status":"OK"},
        "multi_timeframe":{"frames":frames},
        "perp_okx":{
            "last_price":100.0,"bid_price":99.99,"ask_price":100.01,
            "funding_rate":0.0001,
        },
        "spot":{
            "price":100.0,
            "order_book":{"imbalance":0.20},
            "trade_flow":{"buy_sell_ratio":1.35},
        },
    }
    guards={
        "market_ok":True,"news_ok":True,"critical_news_verified":True,
        "market_stale":False,"trading_halted":False,
    }
    if gold:
        market["gold_macro"]={
            "status":"OK",
            "treasury_yields":{
                "status":"OK",
                "daily_change_bps":{"2y":-3.0,"10y":-4.0},
                "curve_2s10s_bps":20.0,
            },
        }
        guards.update({"xau_session_ok":True,"gold_macro_ok":True,"gold_macro_primary_ok":True})
    return {
        "asset":asset,
        "guards":guards,
        "decision_context":{
            "market":market,
            "news":{"events":[],"summary":{"data_quality":"OK"},"guard":{"critical_news_verified":True}},
        },
        "account_state":{"open_positions":0},
    }

# NET-R friction must be positive and regime must be explicit.
p=package()
reg=adaptive_trainer._market_regime(p)
assert reg.startswith("TREND_UP"),reg
candidate={
    "direction":"LONG","stop_pct":0.30,"spread_pct":0.02,
    "funding_rate":0.0001,"time_horizon_minutes":60,
}
cost=adaptive_trainer._estimated_cost(candidate)
assert cost["total_pct"]>0,cost
assert cost["cost_r"]>0,cost

# DeFi and Gold lab candidates are shadow-only and build without execution code.
d=multi_market_trainer._build_candidate(p,"DEFI","SCALP")
assert d and d["group"]=="DEFI",d
assert d["estimated_cost"]["cost_r"]>0,d
assert d["market_regime"].startswith("TREND_UP"),d

g=multi_market_trainer._build_candidate(package("XAU",True),"GOLD","NORMAL")
assert g and g["group"]=="GOLD",g
assert "GOLD" in g["tags"],g
assert any(x.startswith("US10Y_") for x in g["tags"]),g

# Protocol security event must halt DeFi candidate eligibility.
bad=package()
bad["decision_context"]["news"]["events"]=[{
    "title":"Aave protocol exploit drains funds",
    "summary":"security incident",
    "published_at_utc":multi_market_trainer.now().isoformat(),
}]
halt=multi_market_trainer._security_halt(bad)
assert halt["halt"] is True,halt

# Telegram main menu is compact; modes live in a submenu.
main=[x["text"] for row in telegram_control.keyboard("MAIN")["keyboard"] for x in row]
modes=[x["text"] for row in telegram_control.keyboard("MODES")["keyboard"] for x in row]
assert "🎛 РЕЖИМЫ" in main,main
assert "🟦 NORMAL" not in main,main
assert "🟦 NORMAL" in modes and "🔥 MICRO" in modes and "🧠 AUTO" not in modes,modes

print(json.dumps({
    "status":"OK",
    "will_open_order":False,
    "will_close_order":False,
    "will_call_model":False,
    "net_r_cost_model":"OK",
    "regime_learning":"OK",
    "gold_shadow_trainer":"OK",
    "defi_shadow_trainer":"OK",
    "defi_security_halt":"OK",
    "telegram_submenus":"OK",
},ensure_ascii=False,indent=2))

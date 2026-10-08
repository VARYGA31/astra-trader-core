#!/usr/bin/env python3
import json
import config
import decision_gate
import position_exit_guard
from okx_demo_adapter import OKXDemoAdapter

def synthetic_spot(side):
    if side == "SHORT_CHASE":
        return {
            "price":100.0,
            "ticker_24h":{"low":99.7,"high":110},
            "changes_pct":{"1h":-2.0,"4h":-4.0},
            "indicators":{"rsi14":24.0,"atr_pct":1.0,"ema20":104,"ema50":106,"ema200":108},
            "regimes":{"trend":"BEARISH","momentum":"BEARISH"},
            "order_book":{"imbalance":-0.20},
            "trade_flow":{"buy_sell_ratio":0.70},
        }
    return {
        "price":100.0,
        "ticker_24h":{"low":90,"high":100.3},
        "changes_pct":{"1h":2.0,"4h":4.0},
        "indicators":{"rsi14":76.0,"atr_pct":1.0,"ema20":96,"ema50":94,"ema200":92},
        "regimes":{"trend":"BULLISH","momentum":"BULLISH"},
        "order_book":{"imbalance":0.20},
        "trade_flow":{"buy_sell_ratio":1.40},
    }

out={
    "status":"OK",
    "will_open_order":False,
    "will_close_order":False,
    "config":{
        "short_chase_rsi":config.SHORT_CHASE_RSI,
        "long_chase_rsi":config.LONG_CHASE_RSI,
        "chase_extreme_distance_pct":config.CHASE_EXTREME_DISTANCE_PCT,
        "block_btc_eth_same_direction":config.BLOCK_BTC_ETH_SAME_DIRECTION,
        "stop_loss_cooldown_seconds":config.STOP_LOSS_COOLDOWN_SECONDS,
        "emergency_exit_enabled":config.EMERGENCY_EXIT_ENABLED,
        "exit_market_check_seconds":config.EXIT_MARKET_CHECK_SECONDS,
        "emergency_market_exit_score":config.EMERGENCY_MARKET_EXIT_SCORE,
        "emergency_news_min_confidence":config.EMERGENCY_NEWS_MIN_CONFIDENCE,
    },
    "synthetic_tests":{
        "short_chase":decision_gate.chase_guard_from_spot(synthetic_spot("SHORT_CHASE"),"SHORT"),
        "long_chase":decision_gate.chase_guard_from_spot(synthetic_spot("LONG_CHASE"),"LONG"),
    },
}

if config.EXECUTION_MODE=="okx_demo":
    out["exchange_positions"]=OKXDemoAdapter().exchange_active_summary()
    out["current_market_exit_dry_run"]=position_exit_guard.check_market_exits(dry_run=True)

print(json.dumps(out,ensure_ascii=False,indent=2))

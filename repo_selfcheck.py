#!/usr/bin/env python3
from pathlib import Path
import json,py_compile

required=[
"config.py","asset_map.py","market_snapshot.py",
"news_sources.py","news_verifier.py","telegram_markettwits.py","news_snapshot.py","news_listener.py","news_cache.py",
"micro_market_stream.py","micro_stats.py","micro_second_shadow.py","crypto_shadow_lab.py","trade_universe.py","alpha_factory.py","mission_control.py","model_budget.py","market_scanner.py","agent_council.py",
"decision_context.py","decision_gate.py","mtf_gate.py","scalp_gate.py","strategy_mode.py","performance_guard.py","gold_macro.py","adaptive_client.py","adaptive_engine.py","adaptive_memory.py","adaptive_cost.py","adaptive_stats.py","adaptive_trainer.py","defi_universe.py","multi_market_trainer.py","strategy_tournament.py","risk_engine.py","paper_execution.py","trade_cycle.py",
"position_monitor.py","trade_journal.py","cooldown.py","execution_quality.py","observability.py","analytics_report.py",
"astra_client.py","worker.py","exchange_adapter.py",
"telegram_notifier.py","telegram_control.py","okx_demo_adapter.py","okx_position_monitor.py",
"execution_router.py","demo_ledger.py","exit_news_decider.py","position_exit_guard.py",
"test_strategy_guards.py","test_portfolio_guard.py","test_mtf_strategy.py","test_xau_support.py","test_observability.py","test_transition_mode.py","test_execution_quality.py","test_final_decision_calibration.py","test_scalp_mode.py","test_scalp_v2.py","test_micro_mode.py","test_micro_v2.py","test_micro_second_shadow.py","test_telegram_mode_control.py","test_adaptive_mode.py","test_adaptive_cost.py","test_adaptive_auto_v11.py","test_adaptive_trainer_v2.py","test_multi_market_trainer_v3.py","test_auto_execution_v4.py","test_execution_v4_1_fok.py","test_strategy_tournament_v5.py","test_crypto_shadow_lab.py","test_extended_markets.py","test_alpha_factory.py","test_mission_control.py","test_model_budget.py","test_shadow_agent_council.py","test_demo_ledger_concurrency.py","requirements.txt","railway.toml"
]

missing=[x for x in required if not Path(x).exists()]
syntax={}
for x in required:
    if x.endswith(".py") and Path(x).exists():
        try:
            py_compile.compile(x,doraise=True);syntax[x]="OK"
        except Exception as e:syntax[x]=str(e)

bad={k:v for k,v in syntax.items() if v!="OK"}
print(json.dumps({
    "status":"OK" if not missing and not bad else "FAILED",
    "missing":missing,
    "syntax_errors":bad
},ensure_ascii=False,indent=2))
raise SystemExit(0 if not missing and not bad else 1)

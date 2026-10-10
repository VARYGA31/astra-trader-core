#!/usr/bin/env python3
from pathlib import Path
import json,py_compile

required=[
"config.py","asset_map.py","market_snapshot.py",
"news_sources.py","news_verifier.py","telegram_markettwits.py","news_snapshot.py","news_listener.py",
"decision_context.py","decision_gate.py","mtf_gate.py","performance_guard.py","risk_engine.py","paper_execution.py","trade_cycle.py",
"position_monitor.py","trade_journal.py","cooldown.py",
"astra_client.py","worker.py","exchange_adapter.py",
"telegram_notifier.py","okx_demo_adapter.py","okx_position_monitor.py",
"execution_router.py","demo_ledger.py","exit_news_decider.py","position_exit_guard.py",
"test_strategy_guards.py","test_portfolio_guard.py","test_mtf_strategy.py","requirements.txt","railway.toml"
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

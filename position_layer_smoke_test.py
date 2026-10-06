import os, tempfile, json, subprocess
from pathlib import Path

td = tempfile.mkdtemp(prefix="astra_pos_test_")
os.environ["STATE_DIR"] = td

import config
config.STATE_DIR = td

# Create fake paper state
state = {
    "initial_equity":100.0,
    "account_equity":100.0,
    "free_cash":95.0,
    "realized_pnl":0.0,
    "daily_realized_pnl":0.0,
    "daily_pnl_date":"2099-01-01",
    "open_positions":[],
    "closed_positions":[
        {"asset":"BTC","realized_pnl_usd":1.5},
        {"asset":"ETH","realized_pnl_usd":-0.5},
        {"asset":"BTC","realized_pnl_usd":1.0},
    ],
    "trading_halted":False
}
Path(td,"paper_state.json").write_text(json.dumps(state), encoding="utf-8")

import trade_journal, cooldown
s = trade_journal.summary()
assert s["overall"]["trades"] == 3
assert abs(s["overall"]["net_pnl_usd"] - 2.0) < 1e-9
c = cooldown.set_cd("BTC", 60, "TEST")
assert cooldown.get_cd("BTC")["active"] is True
print(json.dumps({"status":"POSITION_LAYER_SMOKE_OK","trades":s["overall"]["trades"]}))

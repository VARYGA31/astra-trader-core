#!/usr/bin/env python3
"""Pure Telegram mode parser/state test. No Telegram/OKX calls, no orders."""
import json,tempfile
from pathlib import Path
import strategy_mode,telegram_control
old=strategy_mode.FILE
try:
    with tempfile.TemporaryDirectory() as td:
        strategy_mode.FILE=Path(td)/"strategy_mode.json"
        assert telegram_control.parse_mode_command("/normal")=="NORMAL"
        assert telegram_control.parse_mode_command("⚡ SCALP")=="SCALP"
        assert telegram_control.parse_mode_command("🔥 MICRO")=="MICRO"
        assert telegram_control.parse_mode_command("🧠 AUTO")=="AUTO"
        assert telegram_control.parse_mode_command("⏸ PAUSE")=="PAUSED"
        assert "SCALP FUNNEL" in telegram_control._scalp_stats_text(6)
        strategy_mode.set_mode("NORMAL","TEST")
        assert strategy_mode.get_mode()=="NORMAL"
        assert strategy_mode.switch_check("NORMAL","SCALP",0)["allowed"] is True
        assert strategy_mode.switch_check("NORMAL","SCALP",1)["allowed"] is False
        assert strategy_mode.switch_check("NORMAL","MICRO",0)["allowed"] is True
        assert strategy_mode.switch_check("NORMAL","MICRO",1)["allowed"] is False
        assert strategy_mode.switch_check("NORMAL","AUTO",0)["allowed"] is True
        assert strategy_mode.switch_check("NORMAL","AUTO",1)["allowed"] is False
        assert strategy_mode.switch_check("NORMAL","PAUSED",1)["allowed"] is True
        strategy_mode.set_mode("SCALP","TEST")
        assert strategy_mode.get_mode()=="SCALP"
finally:
    strategy_mode.FILE=old
print(json.dumps({
    "status":"OK","will_open_order":False,"will_close_order":False,"will_call_model":False,
    "normal_command":"OK","scalp_command":"OK","micro_command":"OK","auto_command":"OK","pause_command":"OK",
    "switch_with_open_position_blocked":True,"pause_with_open_position_allowed":True,
},ensure_ascii=False,indent=2))

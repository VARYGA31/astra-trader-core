#!/usr/bin/env python3
"""Pure runtime-mode control test. No Telegram/OKX calls, no orders."""
import json,tempfile
from pathlib import Path
import strategy_mode,telegram_control

old=strategy_mode.FILE
try:
    with tempfile.TemporaryDirectory() as td:
        strategy_mode.FILE=Path(td)/"strategy_mode.json"

        assert telegram_control.parse_mode_command("/normal")=="NORMAL"
        assert telegram_control.parse_mode_command("🔥 MICRO")=="MICRO"
        assert telegram_control.parse_mode_command("⏸ PAUSE")=="PAUSED"
        assert telegram_control.parse_mode_command("⚡ SCALP") is None
        assert telegram_control.parse_mode_command("🧠 AUTO") is None

        assert strategy_mode.ALLOWED=={"NORMAL","MICRO","PAUSED"}
        strategy_mode.set_mode("NORMAL","TEST")
        assert strategy_mode.get_mode()=="NORMAL"
        assert strategy_mode.switch_check("NORMAL","MICRO",0)["allowed"] is True
        assert strategy_mode.switch_check("NORMAL","MICRO",1)["allowed"] is False
        assert strategy_mode.switch_check("NORMAL","PAUSED",1)["allowed"] is True
        assert strategy_mode.switch_check("NORMAL","SCALP",0)["allowed"] is False
        assert strategy_mode.switch_check("NORMAL","AUTO",0)["allowed"] is False

        strategy_mode.FILE.write_text(
            json.dumps({"mode":"SCALP","changed_by":"OLD_VERSION"}),
            encoding="utf-8",
        )
        assert strategy_mode.get_mode()=="NORMAL"
        migrated=strategy_mode.load()
        assert migrated["changed_by"]=="MIGRATION_FROM_SCALP"

        try:
            strategy_mode.set_mode("AUTO","TEST")
            raise AssertionError("AUTO must be retired")
        except ValueError:
            pass
finally:
    strategy_mode.FILE=old

print(json.dumps({
    "status":"OK",
    "will_open_order":False,"will_close_order":False,"will_call_model":False,
    "tradable_modes":["NORMAL","MICRO"],
    "pause_mode":"OK",
    "retired_modes":["SCALP","AUTO"],
    "legacy_migration":"OK",
},ensure_ascii=False,indent=2))

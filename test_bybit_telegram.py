#!/usr/bin/env python3
import json
import config
import telegram_notifier

out={"execution_mode":config.EXECUTION_MODE}

tg=telegram_notifier.send_text(
    "✅ ASTRA TEST\nTelegram-уведомления подключены.\nСделки пока не открывались."
)
out["telegram"]=tg.get("status")

try:
    from bybit_testnet_adapter import BybitTestnetAdapter
    a=BybitTestnetAdapter()
    checks={}
    for asset in config.ALLOWED_ASSETS:
        try:
            info=a.instrument(asset)
            checks[asset]={"status":"OK","symbol":a.symbol(asset),"instrument_status":info.get("status")}
        except Exception as e:
            checks[asset]={"status":"FAILED","error":str(e)}
    bal=a.wallet_balance()
    out["bybit_testnet"]={"status":"OK","assets":checks,"wallet_retCode":bal.get("retCode")}
except Exception as e:
    out["bybit_testnet"]={"status":"FAILED","error":str(e)}

print(json.dumps(out,ensure_ascii=False,indent=2))

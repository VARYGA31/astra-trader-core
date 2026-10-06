#!/usr/bin/env python3
import json
import config
import telegram_notifier

out={"execution_mode":config.EXECUTION_MODE}

tg=telegram_notifier.send_text(
    "✅ ASTRA TEST\nTelegram подключён.\nOKX Demo проверяется.\nСделки не открывались."
)
out["telegram"]=tg.get("status")

try:
    from okx_demo_adapter import OKXDemoAdapter
    a=OKXDemoAdapter()

    bal=a.balance()
    cfg=a.account_config()
    cfgrow=(cfg.get("data") or [{}])[0]

    assets={}
    for asset in config.ALLOWED_ASSETS:
        try:
            info=a.instrument(asset)
            qty_test=None
            try:
                qty_test=a.contracts_for_notional(asset,20)[0]
            except Exception as qerr:
                qty_test=f"NOTIONAL_CHECK:{qerr}"
            assets[asset]={
                "status":"OK",
                "instId":a.inst_id(asset),
                "instrument_state":info.get("state"),
                "ctVal":info.get("ctVal"),
                "ctValCcy":info.get("ctValCcy"),
                "lotSz":info.get("lotSz"),
                "minSz":info.get("minSz"),
                "approx_contracts_for_$20":qty_test,
            }
        except Exception as e:
            assets[asset]={"status":"FAILED","error":str(e)}

    out["okx_demo"]={
        "status":"OK",
        "balance_code":bal.get("code"),
        "account_pos_mode":cfgrow.get("posMode"),
        "account_mode":cfgrow.get("acctLv"),
        "assets":assets,
    }
except Exception as e:
    out["okx_demo"]={"status":"FAILED","error":str(e)}

print(json.dumps(out,ensure_ascii=False,indent=2))

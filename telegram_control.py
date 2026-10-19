#!/usr/bin/env python3
"""Authorized Telegram control for ASTRA trading modes.

Only NORMAL and MICRO are tradable. PAUSED blocks new entries while protection
for open positions remains active. Trainer/Tournament stay available as
shadow-only learning tools and cannot place orders.
"""
import json,time
from pathlib import Path
import requests

import config,strategy_mode,telegram_notifier,demo_ledger,micro_stats
import adaptive_memory,adaptive_cost,adaptive_trainer,multi_market_trainer,strategy_tournament
import crypto_shadow_lab
from okx_demo_adapter import OKXDemoAdapter

API="https://api.telegram.org"
OFFSET_FILE=Path(config.STATE_DIR)/"telegram_control_offset.json"
STATE={"status":"STARTING","last_error":None,"last_command":None,"last_update_id":None}

def keyboard(section="MAIN"):
    section=str(section or "MAIN").upper()
    if section=="MODES":
        rows=[
            [{"text":"🟦 NORMAL"},{"text":"🔥 MICRO"}],
            [{"text":"⏸ PAUSE"}],
            [{"text":"⬅️ ГЛАВНАЯ"}],
        ]
    elif section=="MONITOR":
        rows=[
            [{"text":"📊 STATUS"},{"text":"💰 COST"}],
            [{"text":"🔥 MICRO STATS"}],
            [{"text":"⬅️ ГЛАВНАЯ"}],
        ]
    elif section=="LEARNING":
        rows=[
            [{"text":"🏆 TOURNAMENT"},{"text":"🧪 CRYPTO TRAINER"}],
            [{"text":"🧠 BRAIN"},{"text":"🎓 LEARNING"}],
            [{"text":"🔬 SHADOW LAB"}],
            [{"text":"⬅️ ГЛАВНАЯ"}],
        ]
    elif section=="MARKETS":
        rows=[
            [{"text":"🥇 GOLD LAB"},{"text":"🟣 DEFI LAB"}],
            [{"text":"🌐 LAB OVERVIEW"}],
            [{"text":"⬅️ ГЛАВНАЯ"}],
        ]
    else:
        rows=[
            [{"text":"🎛 РЕЖИМЫ"},{"text":"📊 МОНИТОРИНГ"}],
            [{"text":"🧪 ОБУЧЕНИЕ"},{"text":"🌐 РЫНКИ"}],
            [{"text":"⏸ PAUSE"},{"text":"📊 STATUS"}],
        ]
    return {"keyboard":rows,"resize_keyboard":True,"is_persistent":True}

def parse_mode_command(text):
    t=str(text or "").strip().upper()
    mapping={
        "/NORMAL":"NORMAL","/MODE_NORMAL":"NORMAL","🟦 NORMAL":"NORMAL","NORMAL":"NORMAL",
        "/MICRO":"MICRO","/MODE_MICRO":"MICRO","🔥 MICRO":"MICRO","MICRO":"MICRO",
        "/PAUSE":"PAUSED","⏸ PAUSE":"PAUSED","PAUSE":"PAUSED","PAUSED":"PAUSED",
    }
    return mapping.get(t)

def _authorized(chat_id):
    return str(chat_id)==str(config.TELEGRAM_CHAT_ID)

def _summary():
    mode=strategy_mode.get_mode()
    try: ex=OKXDemoAdapter().exchange_active_summary()
    except Exception as e: ex={"open_positions":None,"error":str(e)}
    try: ledger=demo_ledger.status()
    except Exception: ledger={}
    brain="ON" if config.AUTO_DECISION else "OFF"
    execute="ON" if config.AUTO_PAPER_EXECUTION else "OFF"
    icon="🔥" if mode=="MICRO" else "🟦" if mode=="NORMAL" else "⏸"
    shadow=str(crypto_shadow_lab.STATE.get("status") or "—")
    return (
        f"🎛 <b>ASTRA CONTROL</b>\n\n"
        f"Активный режим: {icon} <b>{mode}</b>\n"
        f"Decision engine: <b>{brain}</b>\n"
        f"Trade execution: <b>{execute}</b>\n"
        f"Execution target: <b>{config.EXECUTION_MODE}</b>\n"
        f"Открытых позиций: <b>{ex.get('open_positions','—')}</b>\n"
        f"Demo equity: <b>${float(ledger.get('equity') or 0):.2f}</b>\n\n"
        f"🟦 NORMAL: обычная ASTRA 4H → 1H → 15M\n"
        f"🔥 MICRO v2: 5M → 3M → 1M, OKX-native flow, NET-edge gate, hard exit ≤ {config.MICRO_MAX_HOLD_SECONDS//60} мин\n"
        f"🔬 Shadow learning: <b>{shadow}</b> — Trainer/Tournament учатся, но ордера не открывают.\n"
        f"⏸ PAUSE: новые входы выключены, защита открытой позиции продолжает работать."
    )

def _shadow_text():
    st=dict(crypto_shadow_lab.STATE)
    last=st.get("last_result") or {}
    tr=last.get("trainer") or {}
    tour=last.get("tournament") or {}
    return (
        "🔬 <b>CRYPTO SHADOW LAB</b>\n\n"
        f"Status: <b>{st.get('status')}</b>\n"
        f"Last run: <b>{st.get('last_run_at_utc') or '—'}</b>\n"
        f"Trainer recorded/evaluated: <b>{tr.get('recorded',0)}/{tr.get('evaluated',0)}</b>\n"
        f"Tournament recorded/evaluated: <b>{tour.get('recorded',0)}/{tour.get('evaluated',0)}</b>\n"
        f"Champions: <b>{tour.get('champions',0)}</b>\n"
        f"Model calls: <b>{last.get('model_calls',0)}</b> · Order capability: <b>{last.get('order_capability',False)}</b>"
    )

def _send(text,section="MAIN"):
    return telegram_notifier.send_text(text,reply_markup=keyboard(section))

def _switch(target,source="TELEGRAM"):
    with strategy_mode.RUNTIME_LOCK:
        current=strategy_mode.get_mode()
        try:
            ex=OKXDemoAdapter().exchange_active_summary()
            open_positions=int(ex.get("open_positions",0))
        except Exception as e:
            return _send(
                f"⚠️ Не могу безопасно сменить режим: не удалось проверить позиции OKX.\n<code>{str(e)}</code>",
                "MODES"
            )
        chk=strategy_mode.switch_check(current,target,open_positions)
        if not chk.get("allowed"):
            if chk.get("reason")=="OPEN_POSITION_EXISTS":
                return _send(
                    f"⚠️ Переключение <b>{current} → {target}</b> отклонено.\n"
                    f"Сначала должна закрыться текущая позиция OKX.\n"
                    f"Можно нажать ⏸ PAUSE — мониторинг/SL/TP останутся активны.",
                    "MODES"
                )
            return _send(f"⚠️ Режим не изменён: {chk.get('reason')}","MODES")
        strategy_mode.set_mode(target,changed_by=source)
        icon="🔥" if target=="MICRO" else "🟦" if target=="NORMAL" else "⏸"
        return _send(
            f"{icon} <b>ASTRA {target} ACTIVATED</b>\n\n"
            "Режим сохранён в /data и переживёт Redeploy.",
            "MODES"
        )

def handle_update(update):
    msg=update.get("message") or {}
    chat=msg.get("chat") or {}
    chat_id=chat.get("id")
    if not _authorized(chat_id):
        return {"status":"IGNORED_UNAUTHORIZED"}

    text=str(msg.get("text") or "").strip()
    upper=text.upper(); lower=text.lower()
    STATE["last_command"]=text

    if upper=="⬅️ ГЛАВНАЯ" or lower in {"/menu","/start"}:
        _send(_summary(),"MAIN"); return {"status":"OK","action":"MAIN_MENU"}

    if upper=="🎛 РЕЖИМЫ":
        _send(
            "🎛 <b>ТОРГОВЫЕ РЕЖИМЫ ASTRA</b>\n\n"
            "Доступны только NORMAL и MICRO. PAUSE блокирует новые входы.",
            "MODES"
        )
        return {"status":"OK","action":"MENU_MODES"}

    if upper=="📊 МОНИТОРИНГ":
        _send("📊 <b>МОНИТОРИНГ</b>\n\nСтатус, расходы API и MICRO-воронка.","MONITOR")
        return {"status":"OK","action":"MENU_MONITOR"}

    if upper=="🧪 ОБУЧЕНИЕ":
        _send(
            "🧪 <b>ОБУЧЕНИЕ ASTRA</b>\n\n"
            "Trainer/Tournament работают shadow-only и не имеют доступа к ордерам.",
            "LEARNING"
        )
        return {"status":"OK","action":"MENU_LEARNING"}

    if upper=="🌐 РЫНКИ":
        _send("🌐 <b>РЫНКИ-ЛАБОРАТОРИИ</b>\n\nGold и DeFi остаются shadow-only.","MARKETS")
        return {"status":"OK","action":"MENU_MARKETS"}

    if lower in {"/mode","/help"} or upper=="🎛 MODE":
        _send(_summary(),"MAIN"); return {"status":"OK","action":"STATUS"}
    if lower=="/status" or upper=="📊 STATUS":
        _send(_summary(),"MONITOR"); return {"status":"OK","action":"STATUS"}
    if lower in {"/micro_stats","/microstats"} or upper=="🔥 MICRO STATS":
        _send(micro_stats.telegram_text(6),"MONITOR"); return {"status":"OK","action":"MICRO_STATS"}
    if lower in {"/shadow","/shadow_lab"} or upper=="🔬 SHADOW LAB":
        _send(_shadow_text(),"LEARNING"); return {"status":"OK","action":"SHADOW_LAB"}
    if lower in {"/brain","/astra_brain"} or upper=="🧠 BRAIN":
        _send(adaptive_memory.brain_text(),"LEARNING"); return {"status":"OK","action":"BRAIN"}
    if lower in {"/learning","/learn"} or upper=="🎓 LEARNING":
        _send(adaptive_memory.learning_text(168),"LEARNING"); return {"status":"OK","action":"LEARNING"}
    if lower in {"/cost","/api_cost","/usage"} or upper=="💰 COST":
        _send(adaptive_cost.telegram_text(),"MONITOR"); return {"status":"OK","action":"COST"}
    if lower in {"/tournament","/champions","/strategy_tournament"} or upper=="🏆 TOURNAMENT":
        _send(strategy_tournament.telegram_text(168),"LEARNING"); return {"status":"OK","action":"TOURNAMENT"}
    if lower in {"/trainer","/train","/trainer_stats"} or upper in {"🧪 TRAINER","🧪 CRYPTO TRAINER"}:
        _send(adaptive_trainer.telegram_text(168),"LEARNING"); return {"status":"OK","action":"TRAINER"}
    if lower in {"/lab","/markets","/lab_stats"} or upper=="🌐 LAB OVERVIEW":
        _send(multi_market_trainer.telegram_text(168),"MARKETS"); return {"status":"OK","action":"LAB"}
    if lower in {"/gold","/gold_lab"} or upper=="🥇 GOLD LAB":
        _send(multi_market_trainer.gold_text(168),"MARKETS"); return {"status":"OK","action":"GOLD_LAB"}
    if lower in {"/defi","/defi_lab"} or upper=="🟣 DEFI LAB":
        _send(multi_market_trainer.defi_text(168),"MARKETS"); return {"status":"OK","action":"DEFI_LAB"}

    if lower in {"/scalp","/mode_scalp","/auto","/mode_auto","/auto_stats","/scalp_stats"} or upper in {"SCALP","AUTO","⚡ SCALP","🧠 AUTO"}:
        _send(
            "ℹ️ SCALP и AUTO больше не являются торговыми режимами. "
            "Доступны 🟦 NORMAL и 🔥 MICRO; обучение работает отдельно в shadow lab.",
            "MODES"
        )
        return {"status":"OK","action":"RETIRED_MODE_NOTICE"}

    target=parse_mode_command(text)
    if target:
        _switch(target); return {"status":"OK","action":"SWITCH","target":target}

    _send(
        "Главное меню: 🎛 РЕЖИМЫ · 📊 МОНИТОРИНГ · 🧪 ОБУЧЕНИЕ · 🌐 РЫНКИ\n"
        "Команды: /normal /micro /pause /status /cost /micro_stats "
        "/shadow /tournament /trainer /lab /gold /defi /brain /learning",
        "MAIN"
    )
    return {"status":"OK","action":"HELP"}

def _load_offset():
    try:return int(json.loads(OFFSET_FILE.read_text(encoding="utf-8")).get("offset"))
    except Exception:return None

def _save_offset(offset):
    OFFSET_FILE.parent.mkdir(parents=True,exist_ok=True)
    tmp=OFFSET_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"offset":int(offset)}),encoding="utf-8")
    tmp.replace(OFFSET_FILE)

def _get_updates(offset=None,timeout=0):
    url=f"{API}/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates"
    params={"timeout":int(timeout),"allowed_updates":json.dumps(["message"])}
    if offset is not None: params["offset"]=int(offset)
    r=requests.get(url,params=params,timeout=max(10,int(timeout)+8))
    r.raise_for_status()
    d=r.json()
    if not d.get("ok"): raise RuntimeError(str(d))
    return d.get("result",[])

def run_forever():
    if not config.TELEGRAM_CONTROL_ENABLED:
        STATE.update({"status":"DISABLED","last_error":None}); return
    if not (config.TELEGRAM_ENABLED and config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        STATE.update({"status":"DISABLED","last_error":"TELEGRAM_NOT_CONFIGURED"}); return

    offset=_load_offset()
    try:
        if offset is None:
            # On first install skip historical pending commands so a retired
            # mode command cannot unexpectedly affect a fresh deployment.
            old=_get_updates(None,0)
            if old:
                offset=max(int(x.get("update_id",0)) for x in old)+1
                _save_offset(offset)
        STATE.update({"status":"OK","last_error":None})
        _send("🎛 <b>ASTRA Telegram control online</b>\n\n"+_summary(),"MAIN")
    except Exception as e:
        STATE.update({"status":"DEGRADED","last_error":str(e)})

    while True:
        try:
            rows=_get_updates(offset,config.TELEGRAM_CONTROL_POLL_TIMEOUT)
            for u in rows:
                uid=int(u.get("update_id",0))
                handle_update(u)
                offset=uid+1
                STATE["last_update_id"]=uid
                _save_offset(offset)
            STATE.update({"status":"OK","last_error":None})
        except Exception as e:
            STATE.update({"status":"DEGRADED","last_error":str(e)})
            time.sleep(5)

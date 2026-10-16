#!/usr/bin/env python3
"""Authorized Telegram control for ASTRA strategy mode.

The controller never places orders itself. It only changes the persisted active
mode. Switching NORMAL <-> SCALP is refused while an OKX position is open.
PAUSED is always allowed and stops only new entries.
"""
import json,time
from pathlib import Path
import requests
import config,strategy_mode,telegram_notifier,demo_ledger,scalp_stats,adaptive_memory,adaptive_cost,adaptive_stats,adaptive_trainer,multi_market_trainer
from okx_demo_adapter import OKXDemoAdapter

API="https://api.telegram.org"
OFFSET_FILE=Path(config.STATE_DIR)/"telegram_control_offset.json"
STATE={"status":"STARTING","last_error":None,"last_command":None,"last_update_id":None}

def keyboard(section="MAIN"):
    section=str(section or "MAIN").upper()
    if section=="MODES":
        rows=[
            [{"text":"🟦 NORMAL"},{"text":"⚡ SCALP"},{"text":"🧠 AUTO"}],
            [{"text":"⏸ PAUSE"}],
            [{"text":"⬅️ ГЛАВНАЯ"}],
        ]
    elif section=="MONITOR":
        rows=[
            [{"text":"📊 STATUS"},{"text":"💰 COST"}],
            [{"text":"📊 AUTO STATS"},{"text":"📈 SCALP STATS"}],
            [{"text":"⬅️ ГЛАВНАЯ"}],
        ]
    elif section=="LEARNING":
        rows=[
            [{"text":"🧪 CRYPTO TRAINER"},{"text":"🌐 LAB OVERVIEW"}],
            [{"text":"🧠 BRAIN"},{"text":"🎓 LEARNING"}],
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
    return {
        "keyboard":rows,
        "resize_keyboard":True,
        "is_persistent":True,
    }

def parse_mode_command(text):
    t=str(text or "").strip().upper()
    mapping={
        "/NORMAL":"NORMAL","/MODE_NORMAL":"NORMAL","🟦 NORMAL":"NORMAL","NORMAL":"NORMAL",
        "/SCALP":"SCALP","/MODE_SCALP":"SCALP","⚡ SCALP":"SCALP","SCALP":"SCALP",
        "/AUTO":"AUTO","/MODE_AUTO":"AUTO","🧠 AUTO":"AUTO","AUTO":"AUTO",
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
    auto="ON" if config.AUTO_DECISION else "OFF"
    icon="⚡" if mode=="SCALP" else "🟦" if mode=="NORMAL" else "🧠" if mode=="AUTO" else "⏸"
    return (
        f"🎛 <b>ASTRA CONTROL</b>\n\n"
        f"Активный режим: {icon} <b>{mode}</b>\n"
        f"AUTO_DECISION: <b>{auto}</b>\n"
        f"Execution: <b>{config.EXECUTION_MODE}</b>\n"
        f"Открытых позиций: <b>{ex.get('open_positions','—')}</b>\n"
        f"Demo equity: <b>${float(ledger.get('equity') or 0):.2f}</b>\n\n"
        f"🟦 NORMAL: 4H → 1H → 15M\n"
        f"⚡ SCALP: 1H → 15M → 5M (BTC/ETH/GRAM)\n"
        f"🧠 AUTO: Trainer v2 тренируется на 5m без токенов; Astra проверяет только готовые кандидаты\n"
        f"⏸ PAUSE: новые входы выключены, защита открытой позиции продолжает работать."
    )

def _scalp_stats_text(hours=6):
    s=scalp_stats.summary(hours)
    b=s.get("blockers",{})
    tiers=s.get("gate_passes_by_tier",{})
    acts=s.get("model_actions",{})
    lines=[
        f"📈 <b>ASTRA SCALP FUNNEL — {int(float(s.get('hours',hours)))}h</b>",
        "",
        f"Проверок: <b>{s.get('checks',0)}</b>",
        f"Gate PRIME: <b>{tiers.get('PRIME',0)}</b>",
        f"Gate FAST: <b>{tiers.get('FAST',0)}</b>",
        f"Astra calls: <b>{s.get('model_calls',0)}</b>",
        f"Astra LONG/SHORT: <b>{acts.get('LONG',0)+acts.get('SHORT',0)}</b>",
        f"Astra WAIT: <b>{s.get('model_waits',0)}</b>",
        f"Открыто сделок: <b>{s.get('opened_trades',0)}</b>",
        f"FOK без fill: <b>{s.get('fok_not_filled',0)}</b>",
        "",
        "<b>Где чаще блокирует:</b>",
    ]
    labels=[("1H_REGIME","1H regime"),("15M_SETUP","15M setup"),("5M_TRIGGER","5M trigger"),("5M_VOLUME","5M volume"),("SPREAD","spread"),("VOLATILITY","volatility"),("MICROSTRUCTURE","microstructure"),("CHASE","anti-chase"),("GUARD","news/guard"),("SAME_TRIGGER","same 5m candle"),("QUALITY","quality")]
    shown=0
    for key,label in labels:
        n=int(b.get(key,0) or 0)
        if n:
            lines.append(f"• {label}: <b>{n}</b>"); shown+=1
    if not shown: lines.append("• пока данных недостаточно")
    return "\n".join(lines)

def _send(text,section="MAIN"):
    return telegram_notifier.send_text(text,reply_markup=keyboard(section))

def _switch(target,source="TELEGRAM"):
    # Share one in-process lock with execution. If an order is currently being
    # submitted, mode switching waits until the result is known; then the open
    # position guard decides whether switching is safe.
    with strategy_mode.RUNTIME_LOCK:
        current=strategy_mode.get_mode()
        try:
            ex=OKXDemoAdapter().exchange_active_summary()
            open_positions=int(ex.get("open_positions",0))
        except Exception as e:
            return _send(f"⚠️ Не могу безопасно сменить режим: не удалось проверить позиции OKX.\n<code>{str(e)}</code>","MODES")
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
        icon="⚡" if target=="SCALP" else "🟦" if target=="NORMAL" else "🧠" if target=="AUTO" else "⏸"
        return _send(f"{icon} <b>ASTRA {target} ACTIVATED</b>\n\nРежим сохранён в /data и переживёт Redeploy.","MODES")

def handle_update(update):
    msg=update.get("message") or {}
    chat=msg.get("chat") or {}
    chat_id=chat.get("id")
    if not _authorized(chat_id):
        return {"status":"IGNORED_UNAUTHORIZED"}
    text=str(msg.get("text") or "").strip()
    upper=text.upper()
    lower=text.lower()
    STATE["last_command"]=text

    if upper=="⬅️ ГЛАВНАЯ" or lower in {"/menu","/start"}:
        _send(_summary(),"MAIN"); return {"status":"OK","action":"MAIN_MENU"}

    if upper=="🎛 РЕЖИМЫ":
        _send("🎛 <b>РЕЖИМЫ ASTRA</b>\n\nВыбери режим торговли. PAUSE блокирует только новые входы.","MODES")
        return {"status":"OK","action":"MENU_MODES"}
    if upper=="📊 МОНИТОРИНГ":
        _send("📊 <b>МОНИТОРИНГ</b>\n\nСтатус, расходы API и воронка решений.","MONITOR")
        return {"status":"OK","action":"MENU_MONITOR"}
    if upper=="🧪 ОБУЧЕНИЕ":
        _send("🧪 <b>ОБУЧЕНИЕ ASTRA</b>\n\nCrypto Trainer, внешняя память и Multi-Market Lab.","LEARNING")
        return {"status":"OK","action":"MENU_LEARNING"}
    if upper=="🌐 РЫНКИ":
        _send("🌐 <b>РЫНКИ-ЛАБОРАТОРИИ</b>\n\nGold и DeFi сейчас обучаются только на shadow-сделках.","MARKETS")
        return {"status":"OK","action":"MENU_MARKETS"}

    if lower in {"/mode","/help"} or upper=="🎛 MODE":
        _send(_summary(),"MAIN"); return {"status":"OK","action":"STATUS"}
    if lower=="/status" or upper=="📊 STATUS":
        _send(_summary(),"MONITOR"); return {"status":"OK","action":"STATUS"}
    if lower in {"/scalp_stats","/scalpstats"} or upper=="📈 SCALP STATS":
        _send(_scalp_stats_text(6),"MONITOR"); return {"status":"OK","action":"SCALP_STATS"}
    if lower in {"/brain","/astra_brain"} or upper=="🧠 BRAIN":
        _send(adaptive_memory.brain_text(),"LEARNING"); return {"status":"OK","action":"BRAIN"}
    if lower in {"/learning","/learn"} or upper=="🎓 LEARNING":
        _send(adaptive_memory.learning_text(168),"LEARNING"); return {"status":"OK","action":"LEARNING"}
    if lower in {"/cost","/api_cost","/usage"} or upper=="💰 COST":
        _send(adaptive_cost.telegram_text(),"MONITOR"); return {"status":"OK","action":"COST"}
    if lower in {"/auto_stats","/autostats","/auto_funnel"} or upper=="📊 AUTO STATS":
        _send(adaptive_stats.telegram_text(24),"MONITOR"); return {"status":"OK","action":"AUTO_STATS"}
    if lower in {"/trainer","/train","/trainer_stats"} or upper in {"🧪 TRAINER","🧪 CRYPTO TRAINER"}:
        _send(adaptive_trainer.telegram_text(168),"LEARNING"); return {"status":"OK","action":"TRAINER"}
    if lower in {"/lab","/markets","/lab_stats"} or upper=="🌐 LAB OVERVIEW":
        _send(multi_market_trainer.telegram_text(168),"MARKETS"); return {"status":"OK","action":"LAB"}
    if lower in {"/gold","/gold_lab"} or upper=="🥇 GOLD LAB":
        _send(multi_market_trainer.gold_text(168),"MARKETS"); return {"status":"OK","action":"GOLD_LAB"}
    if lower in {"/defi","/defi_lab"} or upper=="🟣 DEFI LAB":
        _send(multi_market_trainer.defi_text(168),"MARKETS"); return {"status":"OK","action":"DEFI_LAB"}

    target=parse_mode_command(text)
    if target:
        _switch(target); return {"status":"OK","action":"SWITCH","target":target}

    _send(
        "Главное меню: 🎛 РЕЖИМЫ · 📊 МОНИТОРИНГ · 🧪 ОБУЧЕНИЕ · 🌐 РЫНКИ\n"
        "Команды: /normal /scalp /auto /pause /status /cost /auto_stats "
        "/scalp_stats /trainer /lab /gold /defi /brain /learning",
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
            # On first install skip historical pending commands so an old /scalp
            # cannot unexpectedly switch the bot after deployment.
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

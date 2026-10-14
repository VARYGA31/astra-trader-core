#!/usr/bin/env python3
import html
import json
from pathlib import Path
from datetime import datetime, timezone
import requests
import config

API = "https://api.telegram.org"
DEDUPE = Path(config.STATE_DIR) / "telegram_event_dedupe.json"

def _fmt_num(v, digits=8):
    if v is None:
        return "—"
    try:
        x = float(v)
        s = f"{x:.{digits}f}".rstrip("0").rstrip(".")
        return s
    except Exception:
        return str(v)

def _load_dedupe():
    try:
        return json.loads(DEDUPE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _claim_event(event_id):
    if not event_id:
        return True
    d = _load_dedupe()
    if event_id in d:
        return False
    d[event_id] = datetime.now(timezone.utc).isoformat()
    if len(d) > 2000:
        d = dict(list(d.items())[-2000:])
    DEDUPE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DEDUPE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DEDUPE)
    return True

def send_text(text, reply_markup=None):
    if not config.TELEGRAM_ENABLED:
        return {"status":"DISABLED"}
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return {"status":"FAILED","reason":"TELEGRAM_CREDENTIALS_MISSING"}
    url = f"{API}/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        payload={
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"]=reply_markup
        r = requests.post(url, json=payload, timeout=12)
        data = r.json()
        return {"status":"OK" if data.get("ok") else "FAILED","response":data}
    except Exception as e:
        return {"status":"FAILED","reason":str(e)}

def _strategy_header(trade):
    mode=str(trade.get("strategy_mode") or "NORMAL").upper()
    if mode=="SCALP":
        return "⚡ <b>ASTRA SCALP</b>"
    return "🟦 <b>ASTRA NORMAL</b>"

def notify_open(trade):
    side = str(trade.get("side","")).upper()
    icon = "🟢" if side in {"LONG","BUY"} else "🔴"
    tier_line=(f"SCALP tier: <b>{html.escape(str(trade.get('scalp_tier','PRIME')))}</b>\n" if str(trade.get("strategy_mode") or "").upper()=="SCALP" else "")
    text = (
        f"{icon} {_strategy_header(trade)} — <b>ПОЗИЦИЯ ОТКРЫТА</b>\n\n"
        f"Монета: <b>{html.escape(str(trade.get('asset','—')))}</b>\n"
        f"Направление: <b>{html.escape(side)}</b>\n"
        f"Таймфрейм: <b>{html.escape(str(trade.get('timeframe',config.TRADING_TIMEFRAME)))}</b>\n"
        f"{tier_line}"
        f"Вход: <b>{_fmt_num(trade.get('entry'))}</b>\n"
        f"Сумма позиции: <b>${_fmt_num(trade.get('notional_usd'),2)}</b>\n"
        f"Маржа: <b>${_fmt_num(trade.get('margin_usd'),2)}</b>\n"
        f"Плечо: <b>{_fmt_num(trade.get('leverage'),2)}x</b>\n"
        f"Stop Loss: <b>{_fmt_num(trade.get('stop_loss'))}</b>\n"
        f"TP1: <b>{_fmt_num(trade.get('take_profit_1'))}</b>\n"
        f"TP2: <b>{_fmt_num(trade.get('take_profit_2'))}</b>\n"
        f"Режим: <b>{html.escape(str(trade.get('mode','—')))}</b>\n"
        f"Order ID: <code>{html.escape(str(trade.get('order_id','—')))}</code>"
    )
    return send_text(text)

def notify_partial(trade):
    event_id = trade.get("partial_event_id")
    if event_id and not _claim_event("PARTIAL:"+str(event_id)):
        return {"status":"DUPLICATE_SUPPRESSED"}
    text = (
        f"🟡 {_strategy_header(trade)} — <b>ЧАСТИЧНОЕ ЗАКРЫТИЕ</b>\n\n"
        f"Монета: <b>{html.escape(str(trade.get('asset','—')))}</b>\n"
        f"Причина: <b>{html.escape(str(trade.get('reason','TP1')))}</b>\n"
        f"Цена: <b>{_fmt_num(trade.get('exit_price'))}</b>\n"
        f"Закрыто: <b>{_fmt_num(trade.get('closed_qty'))}</b>\n"
        f"Остаток: <b>{_fmt_num(trade.get('remaining_qty'))}</b>"
    )
    return send_text(text)

def notify_close(trade):
    event_id = trade.get("close_event_id") or f"{trade.get('asset')}:{trade.get('order_id')}"
    if event_id and not _claim_event("CLOSE:"+str(event_id)):
        return {"status":"DUPLICATE_SUPPRESSED"}

    pnl = trade.get("pnl_usd")
    pnl_icon = "✅" if (pnl is not None and float(pnl) >= 0) else "❌"
    text = (
        f"{pnl_icon} {_strategy_header(trade)} — <b>ПОЗИЦИЯ ЗАКРЫТА</b>\n\n"
        f"Монета: <b>{html.escape(str(trade.get('asset','—')))}</b>\n"
        f"Направление: <b>{html.escape(str(trade.get('side','—')))}</b>\n"
        f"Таймфрейм: <b>{html.escape(str(trade.get('timeframe',config.TRADING_TIMEFRAME)))}</b>\n"
        f"{tier_line}"
        f"Вход: <b>{_fmt_num(trade.get('entry'))}</b>\n"
        f"Выход: <b>{_fmt_num(trade.get('exit_price'))}</b>\n"
        f"Сумма позиции: <b>${_fmt_num(trade.get('notional_usd'),2)}</b>\n"
        f"Плечо: <b>{_fmt_num(trade.get('leverage'),2)}x</b>\n"
        f"PnL: <b>${_fmt_num(pnl,2)}</b>\n"
        f"Причина: <b>{html.escape(str(trade.get('reason','EXCHANGE_CLOSE')))}</b>\n"
        f"Режим: <b>{html.escape(str(trade.get('mode','—')))}</b>"
    )
    return send_text(text)

def notify_system(message, level="INFO"):
    return send_text(f"🤖 <b>ASTRA {html.escape(level)}</b>\n\n{html.escape(str(message))}")

if __name__ == "__main__":
    print(send_text("🤖 ASTRA Telegram notifier: test message"))

#!/usr/bin/env python3
import html
import requests
import config

API = "https://api.telegram.org"

def _fmt_num(v, digits=8):
    if v is None:
        return "—"
    try:
        x = float(v)
        s = f"{x:.{digits}f}".rstrip("0").rstrip(".")
        return s
    except Exception:
        return str(v)

def send_text(text):
    if not config.TELEGRAM_ENABLED:
        return {"status":"DISABLED"}
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return {"status":"FAILED","reason":"TELEGRAM_CREDENTIALS_MISSING"}
    url = f"{API}/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=12)
        data = r.json()
        return {"status":"OK" if data.get("ok") else "FAILED","response":data}
    except Exception as e:
        return {"status":"FAILED","reason":str(e)}

def notify_open(trade):
    side = str(trade.get("side","")).upper()
    icon = "🟢" if side in {"LONG","BUY"} else "🔴"
    text = (
        f"{icon} <b>ASTRA — ПОЗИЦИЯ ОТКРЫТА</b>\n\n"
        f"Монета: <b>{html.escape(str(trade.get('asset','—')))}</b>\n"
        f"Направление: <b>{html.escape(side)}</b>\n"
        f"Таймфрейм: <b>{html.escape(str(trade.get('timeframe',config.TRADING_TIMEFRAME)))}</b>\n"
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
    text = (
        f"🟡 <b>ASTRA — ЧАСТИЧНОЕ ЗАКРЫТИЕ</b>\n\n"
        f"Монета: <b>{html.escape(str(trade.get('asset','—')))}</b>\n"
        f"Причина: <b>{html.escape(str(trade.get('reason','TP1')))}</b>\n"
        f"Цена: <b>{_fmt_num(trade.get('exit_price'))}</b>\n"
        f"Закрыто: <b>{_fmt_num(trade.get('closed_qty'))}</b>\n"
        f"Остаток: <b>{_fmt_num(trade.get('remaining_qty'))}</b>"
    )
    return send_text(text)

def notify_close(trade):
    pnl = trade.get("pnl_usd")
    pnl_icon = "✅" if (pnl is not None and float(pnl) >= 0) else "❌"
    text = (
        f"{pnl_icon} <b>ASTRA — ПОЗИЦИЯ ЗАКРЫТА</b>\n\n"
        f"Монета: <b>{html.escape(str(trade.get('asset','—')))}</b>\n"
        f"Направление: <b>{html.escape(str(trade.get('side','—')))}</b>\n"
        f"Таймфрейм: <b>{html.escape(str(trade.get('timeframe',config.TRADING_TIMEFRAME)))}</b>\n"
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

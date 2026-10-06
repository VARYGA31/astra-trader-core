#!/usr/bin/env python3
import sys, json, hashlib
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup

import config
from news_verifier import classify_event, impact_hint

UA={"User-Agent":"Mozilla/5.0 ASTRA-Trader-News/1.0"}

def clean(x):
    return " ".join((x or "").replace("\n"," ").split())

def fetch():
    r=requests.get(config.MARKETTWITS_URL,headers=UA,timeout=15)
    r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser")
    out=[]
    for wrap in soup.select(".tgme_widget_message_wrap"):
        msg=wrap.select_one(".tgme_widget_message")
        body=wrap.select_one(".tgme_widget_message_text")
        time_el=wrap.select_one("time")
        link=wrap.select_one("a.tgme_widget_message_date")
        if not msg or not body: continue
        post_id=msg.get("data-post","")
        text=clean(body.get_text(" ",strip=True))
        dt=time_el.get("datetime") if time_el else None
        url=link.get("href") if link else (f"https://t.me/{post_id}" if post_id else config.MARKETTWITS_URL)
        title=text[:220]
        eid=hashlib.sha256((post_id+"|"+text).encode()).hexdigest()[:16]
        out.append({
            "id":eid,
            "asset_scope":["BTC","ETH","GRAM"],
            "source":"MarketTwits Telegram",
            "source_id":"telegram_markettwits",
            "tier":3,
            "kind":"TELEGRAM_DISCOVERY",
            "verification_status":"DISCOVERY_ONLY",
            "published_at_utc":dt,
            "title":title,
            "summary":text[:1200],
            "url":url,
            "event_type":classify_event(title,text),
            "impact_hint":impact_hint(title,text,3),
            "discovery_only":True,
            "trade_usable":False,
        })
    return out

if __name__=="__main__":
    try:
        events=fetch()
        print(json.dumps({"status":"OK","source":"MarketTwits Telegram","events":events,"count":len(events)},ensure_ascii=False,separators=(",",":")))
    except Exception as e:
        print(json.dumps({"status":"FAILED","source":"MarketTwits Telegram","error":str(e)},ensure_ascii=False))
        raise SystemExit(1)

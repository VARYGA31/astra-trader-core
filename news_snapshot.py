#!/usr/bin/env python3
import sys,json,time,hashlib,re
from datetime import datetime,timezone,timedelta
from urllib.parse import quote_plus
import feedparser

import config
from news_sources import SOURCES,DISCOVERY_QUERIES,ALIASES,TRUSTED_DISCOVERY_PUBLISHERS
from news_verifier import impact_hint,classify_event,apply_corroboration
import telegram_markettwits

UA={"User-Agent":"ASTRA-Trader-News/2.0"}

def dt_of(e):
    for k in ("published_parsed","updated_parsed","created_parsed"):
        st=getattr(e,k,None)
        if st:return datetime.fromtimestamp(time.mktime(st),tz=timezone.utc)
    return None

def clean(s):return " ".join((s or "").replace("\n"," ").split())

def relevant(asset,text):
    t=(text or "").lower()
    if any(x in t for x in ALIASES[asset]):return True
    if asset=="XAU":
        return any(x in t for x in [
            "fed","interest rate","inflation","jobs","payroll","treasury",
            "yield","dollar","war","attack","sanction","geopolit"
        ])
    return any(x in t for x in [
        "crypto","cryptocurrency","digital asset","etf",
        "federal reserve","sec ","bitcoin","ethereum"
    ])

def eid(source,title,url):
    return hashlib.sha256(f"{source}|{title}|{url}".encode()).hexdigest()[:16]

def rss_events(src,asset,cutoff):
    parsed=feedparser.parse(src["url"],request_headers=UA)
    out=[]
    for e in parsed.entries[:60]:
        title=clean(getattr(e,"title","")); summary=clean(getattr(e,"summary","")); dt=dt_of(e)
        if dt and dt<cutoff:continue

        text=title+" "+summary
        if src["category"] not in {"MACRO","REGULATION"} and not relevant(asset,text):
            continue
        # For XAU, primary macro feeds may contain many unrelated releases.
        if asset=="XAU" and src["category"]=="MACRO" and src["id"] in {"bls_latest","bea"} and not relevant(asset,text):
            continue

        out.append({
            "id":eid(src["id"],title,getattr(e,"link","")),
            "asset":asset,"source":src["name"],"source_id":src["id"],"tier":src["tier"],"kind":src["kind"],
            "verification_status":"PRIMARY" if src["kind"]=="PRIMARY" else "SECONDARY",
            "published_at_utc":dt.isoformat() if dt else None,"title":title,"summary":summary[:900],
            "url":getattr(e,"link",""),"event_type":classify_event(title,summary),
            "impact_hint":impact_hint(title,summary,src["tier"]),"discovery_only":False,
        })
    return out, {"source_id":src["id"],"success":not bool(getattr(parsed,"bozo",False)),"entries":len(parsed.entries)}

def discovery(asset,cutoff):
    out=[]
    for q in DISCOVERY_QUERIES[asset]:
        url=f"https://news.google.com/rss/search?q={quote_plus(q)}&hl=en-US&gl=US&ceid=US:en"
        p=feedparser.parse(url,request_headers=UA)
        for e in p.entries[:15]:
            title=clean(getattr(e,"title","")); summary=clean(getattr(e,"summary","")); dt=dt_of(e)
            if dt and dt<cutoff:continue
            if not relevant(asset,title+" "+summary):continue
            publisher=title.rsplit(" - ",1)[-1] if " - " in title else ""
            status="TRUSTED_DISCOVERY" if publisher in TRUSTED_DISCOVERY_PUBLISHERS else "DISCOVERY_ONLY"
            out.append({
                "id":eid("google",title,getattr(e,"link","")),"asset":asset,"source":publisher or "Google News",
                "source_id":"google_"+(publisher.lower().replace(" ","_") if publisher else "discovery"),
                "tier":2 if status=="TRUSTED_DISCOVERY" else 3,"kind":"DISCOVERY",
                "verification_status":status,"published_at_utc":dt.isoformat() if dt else None,
                "title":title,"summary":summary[:600],"url":getattr(e,"link",""),
                "event_type":classify_event(title,summary),"impact_hint":impact_hint(title,summary,3),
                "discovery_only":True,
            })
    return out

def telegram_events(asset,cutoff):
    out=[]
    raw=telegram_markettwits.fetch()
    for e in raw:
        dt=None
        try:dt=datetime.fromisoformat((e.get("published_at_utc") or "").replace("Z","+00:00"))
        except:pass
        if dt and dt<cutoff:continue
        text=(e.get("title","")+" "+e.get("summary","")).lower()
        allowed_types={"MACRO","GEOPOLITICS","REGULATION"}
        if asset=="XAU":
            allowed_types={"MACRO","GEOPOLITICS","COMMODITY_GOLD"}
        if not relevant(asset,text) and e.get("event_type") not in allowed_types:
            continue
        x=dict(e);x["asset"]=asset;out.append(x)
    return out

def dedupe(events):
    seen=set();out=[]
    for e in sorted(events,key=lambda x:x.get("published_at_utc") or "",reverse=True):
        key=re.sub(r"\W+"," ",e.get("title","").lower()).strip()
        if key in seen:continue
        seen.add(key);out.append(e)
    return out

def _fresh_for_block(e,now):
    ts=e.get("published_at_utc")
    if not ts:return False
    try:
        dt=datetime.fromisoformat(ts.replace("Z","+00:00"))
        return (now-dt).total_seconds() <= config.NEWS_BLOCK_MINUTES*60
    except Exception:
        return False

def snapshot(asset,hours=12):
    if asset not in ALIASES:return {"status":"TRADE_NOT_ALLOWED","requested_asset":asset}

    now=datetime.now(timezone.utc)
    cutoff=now-timedelta(hours=hours)
    events=[]; health=[]

    for src in SOURCES:
        if asset not in src["assets"]:continue
        try:
            ev,h=rss_events(src,asset,cutoff);events+=ev;health.append(h)
        except Exception as e:
            health.append({"source_id":src["id"],"success":False,"error":str(e)})

    try:
        te=telegram_events(asset,cutoff);events+=te
        health.append({"source_id":"telegram_markettwits","success":True,"entries":len(te)})
    except Exception as e:
        health.append({"source_id":"telegram_markettwits","success":False,"error":str(e)})

    try:
        events+=discovery(asset,cutoff)
        health.append({"source_id":"google_discovery","success":True})
    except Exception as e:
        health.append({"source_id":"google_discovery","success":False,"error":str(e)})

    events=apply_corroboration(dedupe(events))[:50]
    high=[e for e in events if e.get("impact_hint")=="HIGH"]
    unresolved=[e for e in high if not e.get("trade_usable")]
    blocking=[e for e in unresolved if _fresh_for_block(e,now)]

    successes=sum(1 for h in health if h.get("success"))
    quality="OK" if successes>=config.MIN_NEWS_SOURCE_SUCCESSES else "FAILED"

    macro_primary_ids={"fed","bls_latest","bea"}
    macro_primary_successes=sum(
        1 for h in health if h.get("source_id") in macro_primary_ids and h.get("success")
    )
    macro_primary_ok=(macro_primary_successes>=2) if asset=="XAU" else True

    return {
        "status":"OK" if quality=="OK" else "FAILED",
        "asset":asset,
        "generated_at_utc":now.isoformat(),
        "lookback_hours":hours,
        "summary":{
            "events_returned":len(events),
            "high_impact_count":len(high),
            "unresolved_high_impact_count":len(unresolved),
            "blocking_unresolved_high_impact_count":len(blocking),
            "source_successes":successes,
            "source_failures":sum(1 for h in health if not h.get("success")),
            "macro_primary_successes":macro_primary_successes if asset=="XAU" else None,
            "data_quality":quality,
        },
        "events":events,
        "source_health":health,
        "guard":{
            "critical_news_verified":len(blocking)==0,
            "unresolved_high_impact":blocking[:10],
            "macro_primary_ok":macro_primary_ok,
        },
    }

if __name__=="__main__":
    asset=(sys.argv[1] if len(sys.argv)>1 else "BTC").upper()
    hours=int(sys.argv[2]) if len(sys.argv)>2 else 12
    print(json.dumps(snapshot(asset,hours),ensure_ascii=False,separators=(",",":")))

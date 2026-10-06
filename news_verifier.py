#!/usr/bin/env python3
import re

HIGH_WORDS = {
    "approval","approved","reject","rejected","ban","banned","lawsuit","charges","charged",
    "hack","hacked","exploit","breach","outage","shutdown","bankruptcy","insolvency",
    "etf","rate cut","rate hike","emergency","sanction","seizure","war","attack","missile",
    "tariff","ceasefire","default","liquidation","security incident","fork","mainnet"
}

STOPWORDS={"the","and","for","with","from","that","this","will","have","has","into","after","about","over",
"что","это","для","как","или","при","после","будет","также","сша","россии","данные"}

def tokens(text):
    return {x for x in re.findall(r"[a-zа-я0-9]{3,}",(text or "").lower()) if x not in STOPWORDS}

def similarity(a,b):
    aa=tokens(a); bb=tokens(b)
    if not aa or not bb:return 0.0
    return len(aa&bb)/len(aa|bb)

def classify_event(title,summary=""):
    t=(title+" "+summary).lower()
    if any(x in t for x in ["sec ","regulat","lawsuit","charges","санкц","регулир"]):return "REGULATION"
    if any(x in t for x in ["federal reserve","fomc","rate cut","rate hike","inflation","cpi","ставк"]):return "MACRO"
    if any(x in t for x in ["hack","exploit","breach","взлом","security incident"]):return "SECURITY"
    if any(x in t for x in ["war","missile","attack","ceasefire","iran","украин","войн","атак","геополит"]):return "GEOPOLITICS"
    if any(x in t for x in ["coinbase","binance","bybit","okx","kraken","exchange","бирж"]):return "EXCHANGE"
    if any(x in t for x in ["upgrade","fork","mainnet","staking","protocol","апгрейд"]):return "PROTOCOL"
    if any(x in t for x in ["ton foundation","the open network","telegram","toncoin"]):return "TELEGRAM_TON"
    if "etf" in t:return "ETF"
    return "GENERAL"

def impact_hint(title,summary="",tier=3):
    t=(title+" "+summary).lower()
    hits=sum(1 for w in HIGH_WORDS if w in t)
    if tier<=1 and hits:return "HIGH"
    if hits>=2:return "HIGH"
    if hits==1:return "MEDIUM"
    return "LOW"

def apply_corroboration(events):
    for e in events:
        if e.get("verification_status")=="PRIMARY":
            e["trade_usable"]=True
            e["corroborated_by"]=[]
            continue
        matches=[]
        if e.get("impact_hint")=="HIGH":
            for other in events:
                if other is e or other.get("source_id")==e.get("source_id"):continue
                if other.get("verification_status") not in {"PRIMARY","SECONDARY","TRUSTED_DISCOVERY"}:continue
                if similarity(e.get("title",""),other.get("title",""))>=0.22:
                    matches.append({"source":other.get("source"),"title":other.get("title"),"status":other.get("verification_status")})
        e["corroborated_by"]=matches[:5]
        e["trade_usable"] = e.get("impact_hint")!="HIGH" or bool(matches)
        if matches and e.get("verification_status") in {"DISCOVERY_ONLY","SECONDARY"}:
            e["verification_status"]="CORROBORATED"
    return events

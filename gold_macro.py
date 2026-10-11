#!/usr/bin/env python3
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import requests

TREASURY_DAILY_XML = "https://home.treasury.gov/sites/default/files/interest-rates/yield.xml"
UA = {"User-Agent":"ASTRA-Trader-Gold-Macro/1.0"}

def _local(tag):
    return tag.rsplit("}",1)[-1] if "}" in tag else tag

def _float(x):
    try:
        return float(x)
    except Exception:
        return None

def treasury_yields():
    r = requests.get(TREASURY_DAILY_XML, headers=UA, timeout=15)
    r.raise_for_status()
    root = ET.fromstring(r.content)

    rows=[]
    for elem in root.iter():
        if _local(elem.tag) != "properties":
            continue
        d={}
        for c in list(elem):
            d[_local(c.tag)] = c.text
        date = d.get("NEW_DATE") or d.get("Date")
        y2 = _float(d.get("BC_2YEAR"))
        y10 = _float(d.get("BC_10YEAR"))
        y30 = _float(d.get("BC_30YEAR"))
        if date and (y2 is not None or y10 is not None):
            rows.append({"date":date,"2y":y2,"10y":y10,"30y":y30})

    if not rows:
        raise RuntimeError("TREASURY_XML_NO_ROWS")

    rows = rows[-3:]
    latest = rows[-1]
    prev = rows[-2] if len(rows) >= 2 else None

    def delta_bps(key):
        if not prev or latest.get(key) is None or prev.get(key) is None:
            return None
        return (latest[key] - prev[key]) * 100.0

    return {
        "status":"OK",
        "source":"U.S. Treasury official daily yield curve XML",
        "latest":latest,
        "previous":prev,
        "daily_change_bps":{
            "2y":delta_bps("2y"),
            "10y":delta_bps("10y"),
            "30y":delta_bps("30y"),
        },
        "curve_2s10s_bps":(
            (latest["10y"]-latest["2y"])*100.0
            if latest.get("10y") is not None and latest.get("2y") is not None
            else None
        ),
    }

def snapshot():
    out={
        "status":"OK",
        "generated_at_utc":datetime.now(timezone.utc).isoformat(),
        "treasury_yields":None,
        # No unreliable/free DXY proxy is fabricated.
        "dxy":{"status":"UNAVAILABLE","reason":"NO_RELIABLE_DXY_SOURCE_CONFIGURED"},
    }
    try:
        out["treasury_yields"]=treasury_yields()
    except Exception as e:
        out["status"]="PARTIAL"
        out["treasury_yields"]={"status":"FAILED","error":str(e)}
    return out

if __name__=="__main__":
    print(json.dumps(snapshot(),ensure_ascii=False,indent=2))

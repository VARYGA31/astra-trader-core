#!/usr/bin/env python3
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import requests

TREASURY_XML_ENDPOINT = (
    "https://home.treasury.gov/resource-center/data-chart-center/"
    "interest-rates/pages/xml"
)
UA = {"User-Agent":"ASTRA-Trader-Gold-Macro/1.1"}

def _local(tag):
    return tag.rsplit("}",1)[-1] if "}" in tag else tag

def _float(x):
    try:
        return float(x)
    except Exception:
        return None

def _parse_date(x):
    if not x:
        return None
    s=str(x).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s[:19] if "T" in s else s, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None

def _extract_rows(xml_bytes):
    root=ET.fromstring(xml_bytes)
    rows=[]

    # Treasury XML is an Atom/OData feed. We intentionally ignore namespace
    # prefixes and work from local tag names so schema namespace changes do not
    # break the parser.
    for elem in root.iter():
        if _local(elem.tag).lower() != "properties":
            continue

        d={}
        for c in elem.iter():
            if c is elem:
                continue
            d[_local(c.tag)] = c.text

        date = d.get("NEW_DATE") or d.get("Date") or d.get("DATE")
        y2 = _float(d.get("BC_2YEAR"))
        y10 = _float(d.get("BC_10YEAR"))
        y30 = _float(d.get("BC_30YEAR") or d.get("BC_30YEARDISPLAY"))

        dt=_parse_date(date)
        if dt and (y2 is not None or y10 is not None or y30 is not None):
            rows.append({
                "date":dt.date().isoformat(),
                "_dt":dt,
                "2y":y2,
                "10y":y10,
                "30y":y30,
            })

    rows.sort(key=lambda x:x["_dt"])
    for r in rows:
        r.pop("_dt",None)
    return rows

def _fetch(params):
    r=requests.get(
        TREASURY_XML_ENDPOINT,
        params=params,
        headers=UA,
        timeout=20,
    )
    r.raise_for_status()
    rows=_extract_rows(r.content)
    return rows, r.url

def treasury_yields():
    now=datetime.now(timezone.utc)

    # Prefer the current month to keep the response small. At the start of a
    # month or if Treasury returns no rows, fall back to the full current year.
    month_key=now.strftime("%Y%m")
    year_key=now.strftime("%Y")

    attempts=[
        {
            "data":"daily_treasury_yield_curve",
            "field_tdr_date_value_month":month_key,
        },
        {
            "data":"daily_treasury_yield_curve",
            "field_tdr_date_value":year_key,
        },
    ]

    rows=[]
    used_url=None
    errors=[]
    for params in attempts:
        try:
            rows,used_url=_fetch(params)
            if rows:
                break
            errors.append(f"NO_ROWS:{params}")
        except Exception as e:
            errors.append(f"{type(e).__name__}:{e}")

    if not rows:
        raise RuntimeError("TREASURY_XML_NO_ROWS | " + " | ".join(errors))

    recent=rows[-3:]
    latest=recent[-1]
    prev=recent[-2] if len(recent)>=2 else None

    def delta_bps(key):
        if not prev or latest.get(key) is None or prev.get(key) is None:
            return None
        return round((latest[key]-prev[key])*100.0,4)

    latest_dt=datetime.strptime(latest["date"],"%Y-%m-%d").replace(tzinfo=timezone.utc)
    age_days=(now-latest_dt).total_seconds()/86400.0

    return {
        "status":"OK" if age_days <= 7 else "STALE",
        "source":"U.S. Treasury official Daily Treasury Par Yield Curve XML",
        "source_url":used_url,
        "latest":latest,
        "previous":prev,
        "age_days":round(age_days,2),
        "daily_change_bps":{
            "2y":delta_bps("2y"),
            "10y":delta_bps("10y"),
            "30y":delta_bps("30y"),
        },
        "curve_2s10s_bps":(
            round((latest["10y"]-latest["2y"])*100.0,4)
            if latest.get("10y") is not None and latest.get("2y") is not None
            else None
        ),
    }

def snapshot():
    out={
        "status":"OK",
        "generated_at_utc":datetime.now(timezone.utc).isoformat(),
        "treasury_yields":None,
        # Do not fabricate an intraday dollar-index proxy.
        "dxy":{"status":"UNAVAILABLE","reason":"NO_RELIABLE_DXY_SOURCE_CONFIGURED"},
    }
    try:
        y=treasury_yields()
        out["treasury_yields"]=y
        if y.get("status")!="OK":
            out["status"]="PARTIAL"
    except Exception as e:
        out["status"]="PARTIAL"
        out["treasury_yields"]={"status":"FAILED","error":str(e)}
    return out

if __name__=="__main__":
    print(json.dumps(snapshot(),ensure_ascii=False,indent=2))

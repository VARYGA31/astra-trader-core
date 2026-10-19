#!/usr/bin/env python3
"""MICRO-100 validation scorecard.

The target is deliberately stricter than raw win rate. A strategy cannot pass
by collecting many tiny wins while occasionally taking outsized losses.
"""
import json, math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import config

JOURNAL=Path(config.STATE_DIR)/"trade_journal.jsonl"

def _parse_ts(x):
    try:
        return datetime.fromisoformat(str(x).replace("Z","+00:00"))
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)

def _load_closed():
    rows=[]
    try:
        lines=JOURNAL.read_text(encoding="utf-8").splitlines()
    except Exception:
        return rows
    seen=set()
    for line in lines:
        try:r=json.loads(line)
        except Exception:continue
        if r.get("event")!="OKX_POSITION_CLOSED":continue
        if str(r.get("strategy_mode") or "").upper()!="MICRO":continue
        key=r.get("close_event_id") or (
            str(r.get("asset"))+":"+str(r.get("order_id"))+":"+str(r.get("opened_at_utc"))
        )
        if key in seen:continue
        seen.add(key)
        try:pnl=float(r.get("pnl_usd") or 0)
        except Exception:continue
        entry=_num(r.get("entry"))
        stop=_num(r.get("stop_loss"))
        notional=_num(r.get("notional_usd"))
        risk_usd=None
        if entry and stop is not None and notional and entry>0:
            risk_usd=notional*abs(entry-stop)/entry
        net_r=(pnl/risk_usd) if risk_usd and risk_usd>0 else None
        rows.append({
            **r,
            "_ts":_parse_ts(r.get("timestamp_utc")),
            "_pnl":pnl,
            "_risk_usd":risk_usd,
            "_net_r":net_r,
        })
    rows.sort(key=lambda x:x["_ts"])
    return rows

def _num(x):
    try:return float(x)
    except Exception:return None

def _wilson(wins,n,z=1.96):
    if n<=0:return (0.0,0.0)
    p=wins/n
    den=1+(z*z/n)
    center=(p+z*z/(2*n))/den
    margin=(z*math.sqrt((p*(1-p)+z*z/(4*n))/n))/den
    return max(0.0,center-margin)*100.0,min(1.0,center+margin)*100.0

def _window(rows,size):
    x=rows[-int(size):] if size else list(rows)
    pnls=[r["_pnl"] for r in x]
    rs=[r["_net_r"] for r in x if r.get("_net_r") is not None]
    wins=sum(1 for p in pnls if p>0)
    losses=sum(1 for p in pnls if p<0)
    flat=len(pnls)-wins-losses
    gross_profit=sum(p for p in pnls if p>0)
    gross_loss=abs(sum(p for p in pnls if p<0))
    pf=(gross_profit/gross_loss) if gross_loss>0 else (None if gross_profit<=0 else float("inf"))
    expectancy_usd=(sum(pnls)/len(pnls)) if pnls else 0.0
    expectancy_r=(sum(rs)/len(rs)) if rs else None

    peak=curve=0.0; max_dd=0.0
    for p in pnls:
        curve+=p; peak=max(peak,curve); max_dd=max(max_dd,peak-curve)
    peak_r=curve_r=0.0; max_dd_r=0.0
    for r in rs:
        curve_r+=r; peak_r=max(peak_r,curve_r); max_dd_r=max(max_dd_r,peak_r-curve_r)

    avg_win=(gross_profit/wins) if wins else None
    avg_loss=(gross_loss/losses) if losses else None
    payoff=(avg_win/avg_loss) if avg_win is not None and avg_loss and avg_loss>0 else None
    ci_low,ci_high=_wilson(wins,len(pnls))
    reasons=Counter(str(r.get("reason") or "UNKNOWN") for r in x)
    assets=Counter(str(r.get("asset") or "?") for r in x)

    return {
        "trades":len(pnls),"wins":wins,"losses":losses,"breakeven":flat,
        "win_rate_pct":round(wins/len(pnls)*100.0,2) if pnls else 0.0,
        "win_rate_95ci_pct":[round(ci_low,2),round(ci_high,2)],
        "net_pnl_usd":round(sum(pnls),6),
        "gross_profit_usd":round(gross_profit,6),
        "gross_loss_usd":round(gross_loss,6),
        "profit_factor":None if pf is None else ("INF" if math.isinf(pf) else round(pf,4)),
        "expectancy_usd":round(expectancy_usd,6),
        "expectancy_r":round(expectancy_r,4) if expectancy_r is not None else None,
        "r_coverage_pct":round(len(rs)/len(pnls)*100.0,2) if pnls else 0.0,
        "max_drawdown_usd":round(max_dd,6),
        "max_drawdown_r":round(max_dd_r,4) if rs else None,
        "avg_win_usd":round(avg_win,6) if avg_win is not None else None,
        "avg_loss_usd":round(avg_loss,6) if avg_loss is not None else None,
        "payoff_ratio":round(payoff,4) if payoff is not None else None,
        "by_asset":dict(assets),
        "close_reasons":dict(reasons.most_common()),
    }

def _pf_value(x):
    if x=="INF":return float("inf")
    try:return float(x)
    except Exception:return 0.0

def _criteria(s):
    complete_r=float(s.get("r_coverage_pct") or 0)>=float(config.MICRO_SCORECARD_MIN_R_COVERAGE_PCT)
    return {
        "win_rate":float(s.get("win_rate_pct") or 0)>=float(config.MICRO_TARGET_WIN_RATE_PCT),
        "profit_factor":_pf_value(s.get("profit_factor"))>=float(config.MICRO_TARGET_PROFIT_FACTOR),
        "expectancy_r":s.get("expectancy_r") is not None and float(s["expectancy_r"])>=float(config.MICRO_TARGET_EXPECTANCY_R),
        "max_drawdown_r":s.get("max_drawdown_r") is not None and float(s["max_drawdown_r"])<=float(config.MICRO_MAX_SCORECARD_DRAWDOWN_R),
        "r_coverage":complete_r,
    }

def _passed(c):
    return bool(c) and all(bool(v) for v in c.values())

def summary():
    rows=_load_closed()
    w100=_window(rows,config.MICRO_SCORECARD_WINDOW)
    w300=_window(rows,config.MICRO_SCORECARD_CONFIRM_WINDOW)
    c100=_criteria(w100)
    c300=_criteria(w300)

    n=len(rows)
    if n<int(config.MICRO_SCORECARD_WINDOW):
        status="COLLECTING"
    elif not _passed(c100):
        status="NEEDS_TUNING"
    elif n<int(config.MICRO_SCORECARD_CONFIRM_WINDOW):
        status="MICRO_100_PASSED"
    elif _passed(c300):
        status="VALIDATED"
    else:
        status="RECENT_EDGE_NOT_CONFIRMED"

    return {
        "status":status,
        "total_micro_closed":n,
        "target":{
            "window":int(config.MICRO_SCORECARD_WINDOW),
            "confirmation_window":int(config.MICRO_SCORECARD_CONFIRM_WINDOW),
            "win_rate_pct":float(config.MICRO_TARGET_WIN_RATE_PCT),
            "profit_factor":float(config.MICRO_TARGET_PROFIT_FACTOR),
            "expectancy_r":float(config.MICRO_TARGET_EXPECTANCY_R),
            "max_drawdown_r":float(config.MICRO_MAX_SCORECARD_DRAWDOWN_R),
            "min_r_coverage_pct":float(config.MICRO_SCORECARD_MIN_R_COVERAGE_PCT),
        },
        "last_100":w100,
        "criteria_100":c100,
        "last_300":w300,
        "criteria_300":c300,
    }

def telegram_text():
    s=summary(); w=s["last_100"]; c=s["criteria_100"]; t=s["target"]
    marks=lambda ok:"✅" if ok else "❌"
    remaining=max(0,int(t["window"])-int(w["trades"]))
    pf=w.get("profit_factor")
    lines=[
        "🎯 <b>ASTRA MICRO-100</b>","",
        f"Статус: <b>{s['status']}</b>",
        f"Закрыто MICRO всего: <b>{s['total_micro_closed']}</b>",
        f"В окне: <b>{w['trades']}/{int(t['window'])}</b>"
        + (f" · осталось {remaining}" if remaining else ""),
        "",
        f"{marks(c['win_rate'])} Win rate: <b>{w['win_rate_pct']:.1f}%</b> / цель ≥ {t['win_rate_pct']:.0f}%",
        f"95% CI: <b>{w['win_rate_95ci_pct'][0]:.1f}%–{w['win_rate_95ci_pct'][1]:.1f}%</b>",
        f"{marks(c['profit_factor'])} Profit factor: <b>{pf}</b> / цель ≥ {t['profit_factor']:.2f}",
        f"{marks(c['expectancy_r'])} NET expectancy: <b>{w.get('expectancy_r')}</b>R / цель ≥ +{t['expectancy_r']:.2f}R",
        f"{marks(c['max_drawdown_r'])} Max DD: <b>{w.get('max_drawdown_r')}</b>R / лимит ≤ {t['max_drawdown_r']:.1f}R",
        f"{marks(c['r_coverage'])} R coverage: <b>{w.get('r_coverage_pct'):.1f}%</b>",
        "",
        f"NET PnL окна: <b>${w['net_pnl_usd']:.4f}</b>",
        f"W/L/BE: <b>{w['wins']}/{w['losses']}/{w['breakeven']}</b>",
    ]
    if s["status"]=="MICRO_100_PASSED":
        lines += ["",f"🧪 MICRO-100 пройден. Теперь подтверждаем на {int(t['confirmation_window'])} сделках."]
    elif s["status"]=="VALIDATED":
        lines += ["","🏆 <b>MICRO подтверждён на контрольном окне.</b>"]
    elif s["status"]=="COLLECTING":
        lines += ["","Сейчас ничего не ослабляем: сначала набираем чистую выборку."]
    else:
        failed=[k for k,v in c.items() if not v]
        lines += ["","Требуют улучшения: <b>"+", ".join(failed)+"</b>"]
    return "\n".join(lines)

if __name__=="__main__":
    print(json.dumps(summary(),ensure_ascii=False,indent=2))

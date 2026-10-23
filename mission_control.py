#!/usr/bin/env python3
"""Read-only ASTRA Mission Control payload + futuristic single-page UI."""
import json
from datetime import datetime, timezone

import config
import alpha_factory
import adaptive_trainer
import strategy_tournament
import trade_universe
import micro_stats
import trade_journal
import observability
import model_budget
import agent_council
import market_scanner

READ_ONLY=True

def _now():
    return datetime.now(timezone.utc).isoformat()

def _top(d,n=8):
    if not isinstance(d,dict):return []
    return [{"name":k,"value":v} for k,v in sorted(d.items(),key=lambda kv:(-float(kv[1]),kv[0]))[:n]]

def build_payload(runtime):
    runtime=runtime or {}
    perf=observability.trade_performance(None)
    overall=(perf or {}).get("overall") or {}
    alpha=alpha_factory.summary()
    tournament=strategy_tournament.summary(168) if config.STRATEGY_TOURNAMENT_V5_ENABLED else {"status":"DISABLED","leaderboard":[]}
    trainer=adaptive_trainer.summary(168)
    micro=micro_stats.summary(6)
    journal=trade_journal.summary()
    diag24=observability.diagnostic_digest(24,5)
    funnel24=(diag24 or {}).get("decision_funnel") or {}
    mode=((runtime.get("strategy_mode") or {}).get("mode") or "UNKNOWN")
    position_check=runtime.get("last_position_check") or {}
    open_positions=position_check.get("open_positions")
    if open_positions is None:
        open_positions=(position_check.get("exchange") or {}).get("open_positions")
    return {
        "generated_at_utc":_now(),
        "read_only":True,
        "system":{
            "status":runtime.get("status"),
            "mode":mode,
            "execution_mode":runtime.get("execution_mode"),
            "decision_engine":bool(runtime.get("decision_engine_enabled")),
            "trade_execution":bool(runtime.get("trade_execution_enabled")),
            "open_positions":open_positions,
            "micro_stream":runtime.get("micro_stream") or {},
            "shadow_lab":runtime.get("crypto_shadow_lab") or {},
            "last_error":runtime.get("last_error"),
        },
        "performance":{
            "overall":overall,
            "by_asset":(perf or {}).get("by_asset") or {},
            "by_mode":(perf or {}).get("by_strategy_mode") or {},
            "recent_closed":(journal or {}).get("recent_closed_positions") or [],
        },
        "micro":{
            "stats_6h":micro,
            "second_shadow":runtime.get("micro_second_shadow") or {},
        },
        "research":{
            "alpha_factory":alpha,
            "trainer":trainer,
            "tournament":tournament,
        },
        "universe":trade_universe.summary(),
        "model_budget":model_budget.summary(),
        "shadow_agent_council":agent_council.summary(),
        "market_scanner":market_scanner.summary(),
        "diagnostics":{
            "top_skip_reasons":_top(runtime.get("skip_reasons") or {},10),
            "decision_funnel_24h":funnel24,
            "mtf_blockers_24h":_top(funnel24.get("mtf_blockers") or {},10),
            "mtf_shadow_replay":(diag24 or {}).get("mtf_shadow_replay") or {},
            "last_trade_rejection":runtime.get("last_trade_rejection"),
            "last_approved_trade":runtime.get("last_approved_trade"),
            "last_model_decision":runtime.get("last_model_decision"),
            "last_decisions":runtime.get("last_decisions") or {},
        },
    }

HTML=r'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#070a14">
<title>ASTRA Mission Control</title>
<style>
:root{
  --bg:#050711;--panel:rgba(12,17,35,.68);--panel2:rgba(18,25,49,.58);
  --line:rgba(130,170,255,.16);--text:#eef4ff;--muted:#8f9bb8;
  --cyan:#58e9ff;--violet:#9b7bff;--green:#63ffc6;--red:#ff6688;--amber:#ffd36a;
  --shadow:0 18px 60px rgba(0,0,0,.42);
}
*{box-sizing:border-box} html,body{margin:0;min-height:100%;background:var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif}
body{overflow-x:hidden}
#stars{position:fixed;inset:0;z-index:0;width:100%;height:100%;opacity:.86}
.nebula{position:fixed;inset:-25%;z-index:0;pointer-events:none;filter:blur(70px);opacity:.42;
 background:
 radial-gradient(circle at 28% 35%,rgba(92,62,255,.45),transparent 27%),
 radial-gradient(circle at 72% 28%,rgba(0,219,255,.35),transparent 24%),
 radial-gradient(circle at 62% 74%,rgba(255,50,160,.19),transparent 24%);
 animation:drift 19s ease-in-out infinite alternate}
.scan{position:fixed;inset:0;z-index:1;pointer-events:none;opacity:.13;background:repeating-linear-gradient(0deg,transparent 0 3px,rgba(255,255,255,.04) 4px)}
@keyframes drift{from{transform:translate3d(-2%,-1%,0) scale(1)}to{transform:translate3d(3%,2%,0) scale(1.08)}}
.app{position:relative;z-index:2;max-width:1600px;margin:auto;padding:24px}
header{display:flex;gap:16px;align-items:center;justify-content:space-between;margin-bottom:18px}
.brand{display:flex;align-items:center;gap:14px}
.logo{width:48px;height:48px;border-radius:15px;position:relative;background:linear-gradient(135deg,rgba(88,233,255,.28),rgba(155,123,255,.22));border:1px solid rgba(122,209,255,.35);box-shadow:0 0 35px rgba(88,233,255,.18)}
.logo:before,.logo:after{content:"";position:absolute;border:1px solid var(--cyan);border-radius:50%;inset:9px;animation:pulse 2.6s ease-in-out infinite}
.logo:after{inset:17px;border-color:var(--violet);animation-delay:-1.3s}
@keyframes pulse{50%{transform:scale(1.15);opacity:.35}}
h1{font-size:20px;letter-spacing:.16em;margin:0;font-weight:800} .subtitle{color:var(--muted);font-size:12px;margin-top:4px;letter-spacing:.08em}
.badges{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}
.badge{border:1px solid var(--line);background:rgba(8,13,28,.68);backdrop-filter:blur(15px);padding:8px 11px;border-radius:999px;font-size:11px;letter-spacing:.08em;text-transform:uppercase}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:7px;box-shadow:0 0 14px currentColor}
.good{color:var(--green)}.bad{color:var(--red)}.warn{color:var(--amber)}.cyan{color:var(--cyan)}
.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:14px}
.panel{position:relative;border:1px solid var(--line);background:linear-gradient(150deg,var(--panel),var(--panel2));backdrop-filter:blur(20px);border-radius:20px;box-shadow:var(--shadow);overflow:hidden}
.panel:before{content:"";position:absolute;inset:0;pointer-events:none;background:linear-gradient(110deg,transparent 5%,rgba(255,255,255,.045),transparent 45%);transform:translateX(-100%);animation:sheen 9s infinite}
@keyframes sheen{10%,100%{transform:translateX(120%)}}
.pad{padding:18px}.span3{grid-column:span 3}.span4{grid-column:span 4}.span5{grid-column:span 5}.span7{grid-column:span 7}.span8{grid-column:span 8}.span12{grid-column:span 12}
.label{font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);margin-bottom:9px}
.metric{font-size:28px;font-weight:760;letter-spacing:-.04em}.metric small{font-size:12px;color:var(--muted);font-weight:500}
.metric.green{color:var(--green)}.metric.red{color:var(--red)}
.row{display:flex;justify-content:space-between;align-items:center;gap:12px}.muted{color:var(--muted)}
.title{font-weight:720;font-size:14px;letter-spacing:.04em}.section-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.kpi-sub{font-size:11px;color:var(--muted);margin-top:8px}
.progress{height:4px;border-radius:99px;background:rgba(255,255,255,.06);margin-top:12px;overflow:hidden}.progress i{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,var(--violet),var(--cyan));box-shadow:0 0 16px var(--cyan)}
table{border-collapse:collapse;width:100%;font-size:11px}th{text-align:left;color:var(--muted);font-weight:600;padding:9px 8px;border-bottom:1px solid var(--line)}td{padding:10px 8px;border-bottom:1px solid rgba(130,170,255,.08)}tr:last-child td{border-bottom:0}
.pill{padding:4px 7px;border-radius:999px;border:1px solid var(--line);font-size:9px;letter-spacing:.05em;white-space:nowrap}
.pill.SHADOW_CHAMPION{color:var(--green);border-color:rgba(99,255,198,.3);background:rgba(99,255,198,.06)}
.pill.PROMISING{color:var(--cyan);border-color:rgba(88,233,255,.3)}.pill.DEGRADED,.pill.REJECTED{color:var(--red)}.pill.CHALLENGER{color:var(--amber)}
#constellation{width:100%;height:360px;display:block;border-radius:16px;background:radial-gradient(circle at center,rgba(70,80,160,.08),transparent 60%)}
.legend{display:flex;gap:13px;flex-wrap:wrap;color:var(--muted);font-size:10px;margin-top:7px}
.legend b{width:7px;height:7px;border-radius:50%;display:inline-block;margin-right:5px}
.chips{display:flex;gap:6px;flex-wrap:wrap}.chip{font-size:10px;padding:6px 8px;border:1px solid var(--line);border-radius:9px;color:#c5d0ec;background:rgba(4,8,20,.42)}
.log{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:10px;color:#afbddc;white-space:pre-wrap;word-break:break-word;max-height:240px;overflow:auto;background:rgba(0,0,0,.18);border-radius:13px;padding:12px}
.agent-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}.agent{position:relative;padding:12px;border:1px solid var(--line);border-radius:15px;background:rgba(4,8,20,.36);overflow:hidden}.agent:after{content:"";position:absolute;inset:auto 8px 0 8px;height:2px;background:var(--agentColor,var(--muted));box-shadow:0 0 14px var(--agentColor,var(--muted))}.agent-name{font-size:11px;font-weight:800;letter-spacing:.12em}.agent-role{font-size:9px;color:var(--muted);margin:4px 0 9px}.agent-vote{font-size:18px;font-weight:760}.agent-reason{font-size:9px;color:#aebbd7;margin-top:5px;min-height:24px}.flowline{display:flex;gap:5px;align-items:center;flex-wrap:wrap;margin-top:12px}.flowstep{font-size:9px;padding:6px 8px;border-radius:10px;border:1px solid var(--line);background:rgba(5,9,20,.46)}.arrow{color:#53617d}.score-ring{display:inline-grid;place-items:center;width:54px;height:54px;border-radius:50%;border:1px solid rgba(88,233,255,.35);box-shadow:inset 0 0 20px rgba(88,233,255,.08),0 0 25px rgba(88,233,255,.08);font-size:14px;font-weight:800}.scanner-row{display:grid;grid-template-columns:44px 1fr 52px 58px;gap:8px;align-items:center;padding:8px 0;border-bottom:1px solid rgba(130,170,255,.08);font-size:10px}.scanner-row:last-child{border-bottom:0}.rank{color:var(--muted)}.bar{height:3px;background:rgba(255,255,255,.06);border-radius:99px;overflow:hidden;margin-top:4px}.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--violet),var(--cyan))}
@media(max-width:620px){.agent-grid{grid-template-columns:repeat(2,1fr)}}
.lock{position:fixed;z-index:20;inset:0;display:none;place-items:center;background:rgba(2,4,12,.78);backdrop-filter:blur(16px)}
.lock.on{display:grid}.lockbox{width:min(430px,calc(100vw - 30px));padding:26px;border-radius:23px;border:1px solid rgba(88,233,255,.22);background:rgba(9,13,29,.92);box-shadow:0 30px 90px #000}
input{width:100%;margin-top:14px;border:1px solid rgba(130,170,255,.25);background:#080d1d;color:white;padding:13px 14px;border-radius:12px;outline:none}
button{margin-top:10px;width:100%;border:0;padding:13px;border-radius:12px;background:linear-gradient(90deg,#6758ff,#30d8ff);color:white;font-weight:700;cursor:pointer}
footer{color:#66728e;font-size:10px;text-align:center;padding:24px}
@media(max-width:1050px){.span3{grid-column:span 6}.span4,.span5,.span7,.span8{grid-column:span 12}}
@media(max-width:620px){.app{padding:14px}.span3{grid-column:span 12}header{align-items:flex-start;flex-direction:column}.badges{justify-content:flex-start}.metric{font-size:24px}#constellation{height:300px}}
</style>
</head>
<body>
<canvas id="stars"></canvas><div class="nebula"></div><div class="scan"></div>
<div class="lock" id="lock"><div class="lockbox">
  <div class="label">SECURE TELEMETRY CHANNEL</div>
  <div class="metric">ASTRA ACCESS</div>
  <div class="kpi-sub">Введите Mission Control token. Он хранится только в sessionStorage браузера.</div>
  <input id="tokenInput" type="password" autocomplete="off" placeholder="Access token">
  <button id="unlock">ОТКРЫТЬ MISSION CONTROL</button>
  <div class="kpi-sub" id="lockError"></div>
</div></div>

<div class="app">
<header>
 <div class="brand"><div class="logo"></div><div><h1>ASTRA · MISSION CONTROL</h1><div class="subtitle">ALPHA FACTORY / PORTFOLIO INTELLIGENCE / OKX DEMO</div></div></div>
 <div class="badges"><span class="badge cyan">READ ONLY</span><span class="badge" id="sysBadge"><i class="dot"></i>CONNECTING</span><span class="badge" id="modeBadge">MODE —</span><span class="badge" id="clock">—</span></div>
</header>

<div class="grid">
 <section class="panel pad span3"><div class="label">Net PnL · all history</div><div class="metric" id="netPnl">—</div><div class="kpi-sub" id="tradeCount">—</div></section>
 <section class="panel pad span3"><div class="label">Profit Factor</div><div class="metric" id="pf">—</div><div class="kpi-sub" id="winRate">—</div></section>
 <section class="panel pad span3"><div class="label">Alpha Factory</div><div class="metric" id="alphaCount">—</div><div class="kpi-sub" id="alphaStatus">—</div><div class="progress"><i id="alphaBar" style="width:0%"></i></div></section>
 <section class="panel pad span3"><div class="label">Open positions</div><div class="metric" id="openPos">—</div><div class="kpi-sub" id="execution">—</div></section>
 <section class="panel pad span3"><div class="label">Model budget · UTC day</div><div class="metric" id="modelSpend">—</div><div class="kpi-sub" id="modelBudgetMeta">—</div><div class="progress"><i id="modelBudgetBar" style="width:0%"></i></div></section>

 <section class="panel pad span8">
   <div class="section-head"><div><div class="label">POLARIS</div><div class="title">Strategy Constellation</div></div><div class="muted" id="evidence">— evidence</div></div>
   <canvas id="constellation"></canvas>
   <div class="legend"><span><b style="background:#63ffc6"></b>Shadow Champion</span><span><b style="background:#58e9ff"></b>Promising</span><span><b style="background:#ffd36a"></b>Challenger</span><span><b style="background:#ff6688"></b>Degraded / Rejected</span></div>
 </section>

 <section class="panel pad span4">
   <div class="section-head"><div><div class="label">ACTIVE UNIVERSE</div><div class="title">Markets</div></div></div>
   <div class="chips" id="markets"></div>
   <div style="height:18px"></div>
   <div class="label">Micro · 6h</div>
   <div class="row"><span class="muted">Checks</span><b id="microChecks">—</b></div>
   <div class="row"><span class="muted">Model calls</span><b id="microCalls">—</b></div>
   <div class="row"><span class="muted">Opened</span><b id="microOpened">—</b></div>
   <div class="row"><span class="muted">Net PnL</span><b id="microPnl">—</b></div>
   <div style="height:18px"></div>
   <div class="label">Top blockers</div><div id="blockers"></div>
 </section>

 <section class="panel pad span7">
   <div class="section-head"><div><div class="label">THE COUNCIL · SHADOW</div><div class="title">Six Agents · One Shared System</div></div><div class="row"><span class="score-ring" id="councilScore">—</span></div></div>
   <div class="agent-grid" id="agentGrid"></div>
   <div class="flowline"><span class="flowstep">SCANNER</span><span class="arrow">›</span><span class="flowstep">MTF GATE</span><span class="arrow">›</span><span class="flowstep">COUNCIL</span><span class="arrow">›</span><span class="flowstep">1× SOL</span><span class="arrow">›</span><span class="flowstep">RISK</span><span class="arrow">›</span><span class="flowstep">FOK EXECUTION</span></div>
   <div class="kpi-sub" id="councilMeta">Shadow evidence only — no execution authority.</div>
 </section>

 <section class="panel pad span5">
   <div class="section-head"><div><div class="label">VEGA SCANNER</div><div class="title">Cross-Asset Opportunity Radar</div></div><div class="muted" id="scannerMeta">—</div></div>
   <div id="scannerRows"></div>
   <div class="kpi-sub">Ranking is passive. It does not change the live universe.</div>
 </section>

 <section class="panel pad span7">
  <div class="section-head"><div><div class="label">ALPHA FACTORY v1</div><div class="title">Top empirical genomes</div></div><div class="muted" id="factoryAge">—</div></div>
  <div style="overflow:auto"><table><thead><tr><th>Status</th><th>Scope</th><th>Genes</th><th>OOS n</th><th>OOS R</th><th>PF</th><th>DD</th><th>WF</th></tr></thead><tbody id="genomes"></tbody></table></div>
 </section>

 <section class="panel pad span5">
  <div class="section-head"><div><div class="label">TOURNAMENT</div><div class="title">Archetype leaderboard</div></div></div>
  <div style="overflow:auto"><table><thead><tr><th>Strategy</th><th>n</th><th>R</th><th>PF</th></tr></thead><tbody id="tournament"></tbody></table></div>
 </section>

 <section class="panel pad span4">
  <div class="label">Trainer · 7d</div><div class="metric" id="trainerR">—</div><div class="kpi-sub" id="trainerMeta">—</div>
 </section>
 <section class="panel pad span4">
  <div class="label">Second position shadow</div><div class="metric" id="shadow2">—</div><div class="kpi-sub" id="shadow2Meta">—</div>
 </section>
 <section class="panel pad span4">
  <div class="label">Runtime health</div><div class="metric" id="stream">—</div><div class="kpi-sub" id="streamMeta">—</div>
 </section>

 <section class="panel pad span12">
  <div class="section-head"><div><div class="label">DIAGNOSTICS</div><div class="title">Last decisions / rejection telemetry</div></div></div>
  <div class="log" id="diag">Waiting for telemetry…</div>
 </section>
</div>
<footer>ASTRA Mission Control · telemetry only · no order/risk controls are exposed to this interface</footer>
</div>
<script>
const $=id=>document.getElementById(id);
const fmt=(v,d=2)=>v===null||v===undefined||Number.isNaN(Number(v))?'—':Number(v).toFixed(d);
const money=v=>v===null||v===undefined?'—':(Number(v)>=0?'+':'')+'$'+fmt(v,2);
const getToken=()=>sessionStorage.getItem('astraMissionToken')||'';
function authHeaders(){const t=getToken();return t?{'Authorization':'Bearer '+t}:{}}
async function api(){
  const r=await fetch('/api/mission-control',{headers:authHeaders(),cache:'no-store'});
  if(r.status===401||r.status===503){$('lock').classList.add('on');throw new Error('LOCKED')}
  if(!r.ok)throw new Error('HTTP '+r.status);
  $('lock').classList.remove('on');return r.json();
}
$('unlock').onclick=async()=>{sessionStorage.setItem('astraMissionToken',$('tokenInput').value.trim());$('lockError').textContent='Проверяю…';try{const d=await api();$('lockError').textContent='';render(d)}catch(e){$('lockError').textContent='Доступ не подтверждён';}};
$('tokenInput').addEventListener('keydown',e=>{if(e.key==='Enter')$('unlock').click()});

let latest=null;
function render(d){
 latest=d;
 const s=d.system||{}, p=(d.performance||{}).overall||{}, a=(d.research||{}).alpha_factory||{}, mb=d.model_budget||{}, md=mb.daily||{}, council=d.shadow_agent_council||{}, scanner=d.market_scanner||{};
 $('sysBadge').innerHTML='<i class="dot"></i>'+String(s.status||'UNKNOWN').toUpperCase();
 $('sysBadge').className='badge '+(s.status==='ok'?'good':s.status==='degraded'?'warn':'bad');
 $('modeBadge').textContent='MODE '+(s.mode||'—');
 $('netPnl').textContent=money(p.net_pnl_usd); $('netPnl').className='metric '+(Number(p.net_pnl_usd||0)>=0?'green':'red');
 $('tradeCount').textContent=(p.trades||0)+' trades · '+(p.wins||0)+'W / '+(p.losses||0)+'L';
 $('pf').textContent=fmt(p.profit_factor,2); $('winRate').textContent='Win rate '+fmt(p.win_rate_pct,1)+'% · Avg R '+fmt(p.avg_r,3);
 $('alphaCount').textContent=a.evaluated_genomes||0;
 const champs=(a.shadow_champions||[]).length, prom=(a.promising||[]).length;
 $('alphaStatus').textContent=champs+' shadow champions · '+prom+' promising';
 $('alphaBar').style.width=Math.min(100,Math.max(3,(a.evidence_rows||0)/50))+'%';
 $('openPos').textContent=s.open_positions??'—'; $('execution').textContent=(s.execution_mode||'—')+' · execution '+(s.trade_execution?'ON':'OFF');
 $('modelSpend').textContent=money(md.estimated_cost_usd||0);
 $('modelBudgetMeta').textContent=(md.calls||0)+' / '+(md.max_calls||0)+' calls · '+fmt(md.cost_remaining_usd,2)+' USD left';
 const maxCost=Number(md.max_cost_usd||0), spent=Number(md.estimated_cost_usd||0);
 $('modelBudgetBar').style.width=(maxCost>0?Math.min(100,Math.max(0,spent/maxCost*100)):0)+'%';
 $('evidence').textContent=(a.evidence_rows||0)+' evidence';
 $('factoryAge').textContent=a.snapshot_age_seconds==null?'collecting':'snapshot '+Math.round(a.snapshot_age_seconds)+'s';
 const uni=d.universe||{}; $('markets').innerHTML=(uni.normal_assets||[]).map(x=>'<span class="chip">'+x+'</span>').join('');
 const m=(d.micro||{}).stats_6h||{}; $('microChecks').textContent=m.checks??0;$('microCalls').textContent=m.model_calls??0;$('microOpened').textContent=m.opened_trades??0;$('microPnl').textContent=money(m.realized_net_pnl_usd||0);
 const blockers=(d.diagnostics||{}).top_skip_reasons||[];$('blockers').innerHTML=blockers.slice(0,6).map(x=>'<div class="row"><span class="muted">'+x.name+'</span><b>'+x.value+'</b></div>').join('')||'<span class="muted">нет данных</span>';
 const clast=council.last||{};
 $('councilScore').textContent=clast.council_score==null?'—':Math.round(clast.council_score);
 $('councilMeta').textContent=(clast.asset?clast.asset+' · ':'')+String(clast.status||'COLLECTING')+(clast.target_direction?' · '+clast.target_direction:'')+' · '+(clast.agree_count||0)+' agree / '+(clast.oppose_count||0)+' oppose'+((clast.veto_count||0)?' · '+clast.veto_count+' VETO':'');
 const voteColor=v=>v==='LONG'?'#63ffc6':v==='SHORT'?'#ff6688':'#8f9bb8';
 $('agentGrid').innerHTML=(clast.agents||[]).map(x=>'<div class="agent" style="--agentColor:'+voteColor(x.vote)+'"><div class="agent-name">'+(x.icon||'')+' '+x.agent+'</div><div class="agent-role">'+x.role+'</div><div class="agent-vote" style="color:'+voteColor(x.vote)+'">'+x.vote+(x.veto?' · VETO':'')+'</div><div class="agent-reason">'+x.reason+'</div><div class="kpi-sub">'+fmt(x.confidence,0)+'% confidence</div></div>').join('')||'<div class="muted">Council collecting first observations…</div>';
 const ranks=scanner.ranking||[];$('scannerMeta').textContent=(scanner.fresh_assets||0)+' fresh assets';
 $('scannerRows').innerHTML=ranks.map((x,i)=>'<div class="scanner-row"><span class="rank">#'+(i+1)+'</span><div><b>'+x.asset+'</b><div class="bar"><i style="width:'+Math.min(100,Math.max(0,Number(x.opportunity_score||0)))+'%"></i></div></div><b>'+fmt(x.opportunity_score,0)+'</b><span class="muted">'+(x.spread_pct==null?'—':fmt(x.spread_pct,3)+'%')+'</span></div>').join('')||'<span class="muted">Scanner collecting market observations…</span>';
 const genomes=(a.top_genomes||[]).slice(0,14);
 $('genomes').innerHTML=genomes.map(g=>'<tr><td><span class="pill '+g.status+'">'+g.status+'</span></td><td>'+(g.asset_scope||'*')+' '+g.direction+'</td><td title="'+g.genes.join(' · ')+'">'+g.genes.slice(0,3).join(' · ')+'</td><td>'+g.oos.samples+'</td><td>'+fmt(g.oos.avg_net_r,3)+'</td><td>'+fmt(g.oos.profit_factor,2)+'</td><td>'+fmt(g.oos.max_drawdown_r,2)+'</td><td>'+Math.round(100*(g.walk_forward.positive_ratio||0))+'%</td></tr>').join('')||'<tr><td colspan="8" class="muted">Alpha Factory собирает evidence…</td></tr>';
 const board=((d.research||{}).tournament||{}).leaderboard||[];
 $('tournament').innerHTML=board.slice(0,9).map(x=>'<tr><td>'+x.asset+' '+x.archetype+' '+x.direction+'</td><td>'+x.samples+'</td><td>'+fmt(x.avg_net_r,3)+'</td><td>'+fmt(x.profit_factor,2)+'</td></tr>').join('')||'<tr><td colspan="4" class="muted">нет данных</td></tr>';
 const tr=(d.research||{}).trainer||{};$('trainerR').textContent=fmt(tr.avg_net_r??tr.avg_r,3)+'R';$('trainerMeta').textContent=(tr.evaluated||0)+' evaluated · cost '+fmt(tr.avg_cost_r,3)+'R';
 const sh=(d.micro||{}).second_shadow||{};$('shadow2').textContent=(sh.evaluated||0)+' eval';$('shadow2Meta').textContent=(sh.wins||0)+'W/'+(sh.losses||0)+'L · PF '+fmt(sh.profit_factor,2)+' · NET '+money(sh.net_pnl_usd||0);
 const ws=s.micro_stream||{};$('stream').textContent=String(ws.status||'—');$('streamMeta').textContent='OKX WS '+(ws.connected?'connected':'not connected')+' · Shadow Lab '+String((s.shadow_lab||{}).status||'—');
 const dd=d.diagnostics||{};
 const diag={model_budget:mb,decision_funnel_24h:dd.decision_funnel_24h,mtf_blockers_24h:dd.mtf_blockers_24h,mtf_shadow_replay:dd.mtf_shadow_replay,shadow_agent_council:clast,market_scanner:ranks,last_trade_rejection:dd.last_trade_rejection,last_approved_trade:dd.last_approved_trade,last_model_decision:dd.last_model_decision};
 $('diag').textContent=JSON.stringify(diag,null,2);
 drawConstellation(genomes);
}
async function refresh(){try{render(await api())}catch(e){if(e.message!=='LOCKED'){$('sysBadge').textContent='OFFLINE';$('sysBadge').className='badge bad'}}}
setInterval(()=>{$('clock').textContent=new Date().toLocaleTimeString('ru-RU');},1000);
setInterval(refresh,5000);refresh();

// ambient starfield
const sc=$('stars'),sx=sc.getContext('2d');let stars=[];
function resizeStars(){const d=devicePixelRatio||1;sc.width=innerWidth*d;sc.height=innerHeight*d;sc.style.width=innerWidth+'px';sc.style.height=innerHeight+'px';sx.setTransform(d,0,0,d,0,0);stars=Array.from({length:Math.min(150,Math.floor(innerWidth/9))},()=>({x:Math.random()*innerWidth,y:Math.random()*innerHeight,z:Math.random()*1.8+.2,v:Math.random()*.12+.02}));}
function starLoop(){sx.clearRect(0,0,innerWidth,innerHeight);for(const s of stars){s.y+=s.v*s.z;if(s.y>innerHeight)s.y=0;sx.globalAlpha=.25+.55*s.z/2;sx.fillStyle='#b9d7ff';sx.beginPath();sx.arc(s.x,s.y,s.z*.7,0,Math.PI*2);sx.fill()}requestAnimationFrame(starLoop)}
addEventListener('resize',resizeStars);resizeStars();starLoop();

// strategy constellation
const cc=$('constellation'),cx=cc.getContext('2d');
function color(st){return st==='SHADOW_CHAMPION'?'#63ffc6':st==='PROMISING'?'#58e9ff':st==='CHALLENGER'?'#ffd36a':'#ff6688'}
function drawConstellation(gs){
 const r=cc.getBoundingClientRect(),d=devicePixelRatio||1;cc.width=r.width*d;cc.height=r.height*d;cx.setTransform(d,0,0,d,0,0);cx.clearRect(0,0,r.width,r.height);
 if(!gs.length){cx.fillStyle='#74809e';cx.font='12px system-ui';cx.fillText('Collecting empirical genomes…',20,30);return}
 const nodes=gs.map((g,i)=>{const ang=(i/gs.length)*Math.PI*2-1.1,rad=Math.min(r.width,r.height)*(.18+.18*((i%4)/3));return{x:r.width/2+Math.cos(ang)*rad,y:r.height/2+Math.sin(ang)*rad,g}});
 for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++){const a=nodes[i],b=nodes[j];const same=a.g.genes.some(x=>b.g.genes.includes(x));if(!same)continue;cx.strokeStyle='rgba(110,150,255,.11)';cx.lineWidth=.7;cx.beginPath();cx.moveTo(a.x,a.y);cx.lineTo(b.x,b.y);cx.stroke()}
 nodes.forEach((n,i)=>{const c=color(n.g.status),size=5+Math.min(9,Math.max(0,n.g.score||0)/12);cx.shadowColor=c;cx.shadowBlur=18;cx.fillStyle=c;cx.globalAlpha=.9;cx.beginPath();cx.arc(n.x,n.y,size,0,Math.PI*2);cx.fill();cx.shadowBlur=0;cx.globalAlpha=.8;cx.fillStyle='#dce6ff';cx.font='10px system-ui';cx.fillText((n.g.asset_scope==='*'?'ALL':n.g.asset_scope)+' '+n.g.direction,n.x+size+5,n.y+3)});
 cx.globalAlpha=1;
}
</script>
</body></html>'''

def html():
    return HTML

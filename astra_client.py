import json,re
from pathlib import Path
from datetime import datetime,timezone
from openai import OpenAI
import config
INSTRUCTIONS='''You are ASTRA TRADER's final decision engine.
Trade only BTC, ETH, or GRAM. Return exactly one JSON object.
The deterministic Python guards already validated required system health.
WAIT is mandatory only when guards explicitly block, required market context is unusable, no valid stop/invalidation exists, or reward/risk is unattractive.
Optional data can be unavailable without forcing WAIT. In particular, liquidation data may be unavailable, one secondary news source may fail, and funding/OI may be partial. Lower confidence instead of automatically vetoing unless guards say otherwise.
Never size a position. Risk Engine owns sizing.
Required keys: asset, action, entry, stop_loss, take_profit_1, take_profit_2, confidence, data_quality, volatility_regime, leverage, reason.
action must be LONG, SHORT, or WAIT. confidence is 0-100 analytical confidence, not win probability. For WAIT, entry/stop/take profits must be null. Prefer leverage 3.'''
def extract(text):
    try:return json.loads(text)
    except:
        m=re.search(r'\{.*\}',text,re.S)
        if not m:raise ValueError('Model did not return JSON')
        return json.loads(m.group(0))
def _compact(p):
    dc=p.get('decision_context',{});m=dc.get('market',{});n=dc.get('news',{});ev=[]
    for e in n.get('events',[])[:config.MAX_MODEL_NEWS_EVENTS]:
        ev.append({k:e.get(k) for k in ('id','source','verification_status','published_at_utc','title','event_type','impact_hint','trade_usable')})
    return {'asset':p.get('asset'),'timeframe':p.get('timeframe'),'execution_mode':p.get('execution_mode'),'account_state':p.get('account_state'),'guards':p.get('guards'),'market':{'generated_at_utc':m.get('generated_at_utc'),'spot':m.get('spot'),'perp_okx':m.get('perp_okx'),'liquidations':m.get('liquidations'),'data_quality':m.get('data_quality')},'news':{'summary':n.get('summary'),'guard':n.get('guard'),'events':ev}}
def _log_usage(r,asset):
    u=getattr(r,'usage',None)
    if not u:return
    row={'timestamp_utc':datetime.now(timezone.utc).isoformat(),'asset':asset,'model':config.OPENAI_MODEL,'input_tokens':getattr(u,'input_tokens',None),'output_tokens':getattr(u,'output_tokens',None),'total_tokens':getattr(u,'total_tokens',None)}
    try:
        path=Path(config.STATE_DIR)/'openai_usage.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    except:pass
def decide(package):
    client=OpenAI(); compact=_compact(package)
    kwargs={'input':'Analyze this pre-filtered trading context and return the required JSON only:\n'+json.dumps(compact,ensure_ascii=False,separators=(',',':')),'store':False}
    if config.OPENAI_PROMPT_ID:kwargs['prompt']={'id':config.OPENAI_PROMPT_ID}
    else:
        kwargs['model']=config.OPENAI_MODEL;kwargs['instructions']=INSTRUCTIONS;kwargs['reasoning']={'effort':config.OPENAI_REASONING_EFFORT}
    r=client.responses.create(**kwargs);_log_usage(r,package.get('asset'));d=extract(r.output_text)
    try:
        c=float(d.get('confidence',0));d['confidence']=max(0,min(100,c*100 if 0<=c<=1 else c))
    except:d['confidence']=0.0
    a=str(d.get('action','WAIT')).upper();d['action']=a if a in {'LONG','SHORT','WAIT'} else 'WAIT';d['asset']=str(d.get('asset',package.get('asset',''))).upper();d['timeframe']=d.get('timeframe') or package.get('timeframe') or config.TRADING_TIMEFRAME
    if d['action']=='WAIT':d['entry']=d['stop_loss']=d['take_profit_1']=d['take_profit_2']=None
    return d

#!/usr/bin/env python3
import json
from datetime import datetime,timezone
from pathlib import Path
import config
STATE_FILE=Path(config.STATE_DIR)/"decision_gate_state.json"
def _load():
    try:return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except:return {}
def _save(d):
    STATE_FILE.parent.mkdir(parents=True,exist_ok=True)
    t=STATE_FILE.with_suffix('.tmp');t.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(STATE_FILE)
def _market_score(p):
    m=p.get('decision_context',{}).get('market',{}).get('spot',{})
    rg=m.get('regimes',{}); ind=m.get('indicators',{}); ch=m.get('changes_pct',{}); book=m.get('order_book',{}); flow=m.get('trade_flow',{})
    s=0; r=[]
    if rg.get('trend')=='BULLISH':s+=2;r.append('trend_bullish')
    elif rg.get('trend')=='BEARISH':s-=2;r.append('trend_bearish')
    if rg.get('momentum')=='BULLISH':s+=1;r.append('momentum_bullish')
    elif rg.get('momentum')=='BEARISH':s-=1;r.append('momentum_bearish')
    x=ind.get('rsi14')
    if isinstance(x,(int,float)):
        if x>=58:s+=1;r.append('rsi_positive')
        elif x<=42:s-=1;r.append('rsi_negative')
    x=ch.get('1h')
    if isinstance(x,(int,float)):
        if x>=.25:s+=1;r.append('change_1h_positive')
        elif x<=-.25:s-=1;r.append('change_1h_negative')
    x=ch.get('4h')
    if isinstance(x,(int,float)):
        if x>=.60:s+=1;r.append('change_4h_positive')
        elif x<=-.60:s-=1;r.append('change_4h_negative')
    x=book.get('imbalance')
    if isinstance(x,(int,float)):
        if x>=.12:s+=1;r.append('book_buy_imbalance')
        elif x<=-.12:s-=1;r.append('book_sell_imbalance')
    x=flow.get('buy_sell_ratio')
    if isinstance(x,(int,float)):
        if x>=1.15:s+=1;r.append('aggressive_buy_flow')
        elif x<=.87:s-=1;r.append('aggressive_sell_flow')
    return s,r,m.get('last_candle_close_time_ms')
def _verified_event(p):
    for e in p.get('decision_context',{}).get('news',{}).get('events',[]):
        if e.get('impact_hint')=='HIGH' and e.get('trade_usable'):return e.get('id')
    return None
def evaluate(p,force_event=False):
    g=p.get('guards',{})
    if g.get('market_stale') or not g.get('market_ok') or not g.get('news_ok') or not g.get('critical_news_verified') or g.get('trading_halted') or g.get('cooldown',{}).get('active'):
        return {'call_model':False,'reason':'GUARD_BLOCK'}
    if int(p.get('account_state',{}).get('open_positions',0))>=config.MAX_OPEN_POSITIONS:return {'call_model':False,'reason':'MAX_OPEN_POSITIONS'}
    score,reasons,candle=_market_score(p); ev=_verified_event(p); st=_load(); old=st.get(p.get('asset',''),{})
    new_candle=candle is not None and candle!=old.get('last_candle_close_time_ms'); new_event=ev is not None and ev!=old.get('last_verified_event_id')
    call=bool((new_candle and abs(score)>=config.MODEL_GATE_MIN_SCORE) or new_event or (force_event and ev))
    reason='MODEL_GATE_PASS' if call else ('SAME_CANDLE' if not new_candle and not new_event else 'NO_STRONG_SETUP')
    if call:
        st[p.get('asset','')]={'last_candle_close_time_ms':candle,'last_verified_event_id':ev,'last_gate_score':score,'last_called_at_utc':datetime.now(timezone.utc).isoformat()};_save(st)
    return {'call_model':call,'reason':reason,'score':score,'score_reasons':reasons,'new_candle':new_candle,'new_verified_high_event':new_event}

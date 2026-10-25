#!/usr/bin/env python3
"""Read-only, point-in-time Korean large-cap reversal research.

No brokerage credentials, orders, champion promotion, or runtime DB access.
Inputs: public FinanceData/marcap yearly parquet (raw, NOT split adjusted),
Naver Finance daily KOSPI index historical OHLC.
Outputs: reproducible CSV/JSON summaries. 2026-10-25 research baseline.
"""
import ast
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
import csv
import gzip
import hashlib
import json
import math
import re
import sys

import duckdb
import pandas as pd

ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'
RESULT=ROOT/'results'
RESULT.mkdir(mode=0o700,exist_ok=True)
PATS=str(DATA/'marcap-*.parquet')
BASE_CASH=10_000_000.0
TOP_N=150
TURNOVER=10_000_000_000.0
MIN_HISTORY=200
START='2015-01-02'
END='2026-10-23'
# Flat, CONSERVATIVE fee assumption, NOT actual historical effective tax for each year.
BROKER=0.00015   # 0.015% per side
SELL_TAX=0.002  # fallback 2026 sale tax
TAX_POLICY='historical'  # date-dependent KOSPI sell tax including 0.15% rural special tax
MAX_POSITIONS=5
C_PENETRATION=0.002
C_ENTRY_BUFFER=0.001
C_EXIT_SLIP=0.001
def sale_tax(day):
    if TAX_POLICY == 'flat20': return 0.002
    if TAX_POLICY == 'flat30': return 0.003
    if TAX_POLICY == 'flat35': return 0.0035
    if TAX_POLICY != 'historical':raise ValueError(TAX_POLICY)
    if day < '2019-06-03':return 0.0030
    if day < '2021-01-01':return 0.0025
    if day < '2023-01-01':return 0.0023
    if day < '2024-01-01':return 0.0020
    if day < '2025-01-01':return 0.0018
    if day < '2026-01-01':return 0.0015
    return 0.0020
ENTRY_WEIGHT=0.20
MAX_DAYS=7

def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

def load_index():
    text=(DATA/'kospi-index-naver-2014-2026.txt').read_bytes().decode('utf-8')
    raw=ast.literal_eval(text.strip().rstrip(';'))
    assert len(raw)>=3000 and raw[0][0]=='날짜'
    index=[]
    for row in raw[1:]:
        dt=datetime.strptime(str(row[0]),'%Y%m%d').date().isoformat()
        close=float(row[4])
        if close>0:index.append((dt,close))
    index=sorted(set(index))
    assert index[0][0]<='2014-01-03' and index[-1][0]>=END
    result={}
    rolling=deque(maxlen=200)
    for date,close in index:
        rolling.append(close)
        result[date]={'close':close,'sma200':sum(rolling)/200 if len(rolling)==200 else None}
    return index,result

def ordinary(code,name):
    # Exclude preferred and noncommon instruments with a transparent, IMPERFECT heuristic.
    if not re.fullmatch(r'\d{5}0',code):return False
    if ('스팩' in name or '리츠' in name or 'ETN' in name or 'ETF' in name):return False
    return True

def collect_signals(index_info):
    db=duckdb.connect(database=':memory:')
    db.execute("SET memory_limit='450MB'")
    db.execute(f"SET temp_directory='{ROOT}/duckdb_tmp'")
    db.execute("SET threads=2")
    db.execute(f"""CREATE TEMP VIEW raw_data AS
       SELECT CAST(Date AS DATE) as day, Code AS code, Name AS name,
         Open AS o, High AS h, Low AS l, Close AS c,
         Amount AS amount, Marcap AS cap, Stocks AS shares
       FROM read_parquet('{PATS}') WHERE Market='KOSPI' AND MarketId='STK'
       AND regexp_full_match(Code,'[0-9]{{5}}0')
       AND Name NOT LIKE '%스팩%' AND Name NOT LIKE '%리츠%'
       AND Name NOT LIKE '%ETF%' AND Name NOT LIKE '%ETN%'
       AND Close>0 AND Marcap>0
       """)
    # Cap rank computed over that day's COMMON STOCK universe only. Current-day
    # value is allowed because signals are generated after market close.
    sql="""SELECT day,code,name,o,h,l,c,amount,cap,shares, cap_rank
    FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY day ORDER BY cap DESC,code) AS cap_rank
          FROM raw_data)
    ORDER BY code,day"""
    cur=db.execute(sql)
    candidates=[]
    current=None
    hist=deque(maxlen=200)
    avg_amt=deque(maxlen=20)
    close6=deque(maxlen=6)
    gains=losses=0.0
    diff_count=0
    last_close=last_shares=None
    split_cooldown=0
    stats=defaultdict(int)
    while True:
        rows=cur.fetchmany(8000)
        if not rows:break
        for dt,code,name,o,h,l,c,amount,cap,shares,rank in rows:
            day=dt.isoformat()
            stats['rows_scanned']+=1
            if code!=current:
                current=code
                hist=deque(maxlen=200);avg_amt=deque(maxlen=20);close6=deque(maxlen=6)
                gains=losses=0.0;diff_count=0;last_close=last_shares=None;split_cooldown=0
            split=False
            if last_close and last_shares and shares:
                a=shares/last_shares
                b=last_close/c
                if (a>1.7 or a<0.6) and (b>1.7 or b<0.6) and 0.8 <= a/b <= 1.25:
                    split=True
                    split_cooldown=200
                    stats['corporate_split_events_detected']+=1
            last_shares=shares
            if last_close:
                change=c-last_close
                gain=max(change,0.0);loss=max(-change,0.0)
                if diff_count<2:
                    gains+=gain;losses+=loss;diff_count+=1
                    if diff_count==2:gains/=2;losses/=2
                else:
                    gains=.5*gains+.5*gain
                    losses=.5*losses+.5*loss
            last_close=c
            hist.append(c);close6.append(c);avg_amt.append(amount or 0)
            split_cooldown=max(0,split_cooldown-1)
            if not(START<=day<=END):continue
            if rank>TOP_N:continue
            stats['top150_sessions']+=1
            if len(hist)<200 or len(avg_amt)<20 or len(close6)<6 or diff_count<2:
                stats['insufficient_history']+=1;continue
            if split_cooldown:
                stats['split_200_session_excluded']+=1;continue
            if sum(avg_amt)/20<TURNOVER:
                stats['turnover_excluded']+=1;continue
            idx=index_info.get(day)
            if not idx or idx['sma200'] is None:
                stats['index_missing']+=1;continue
            if idx['close']<=idx['sma200']:
                stats['market_200sma_excluded']+=1;continue
            stats['market_gate_pass']+=1
            if c<=sum(hist)/200:
                stats['stock_200sma_excluded']+=1;continue
            five_day=c/close6[0]-1.0
            if five_day>-0.07:
                stats['five_day_return_excluded']+=1;continue
            rsi=(100.0*gains/(gains+losses)) if (gains+losses)>0 else 50.0
            if rsi>=10.0:
                stats['rsi2_excluded']+=1;continue
            if not (o and h and l and h>=max(o,c)>=l and h>=l):
                stats['malformed_signal_bar']+=1;continue
            stats['entry_signals']+=1
            candidates.append({
                'signal_date':day,'code':code,'name':name,'close':float(c),
                'rsi2_wilder':round(rsi,3),'return5':round(five_day,6),
                'prior_closes':list(close6)[-5:],
                'rank':rank,
            })
    db.close()
    candidates.sort(key=lambda x:(x['signal_date'],x['return5'],x['code']))
    return candidates,dict(stats)

def load_future_bars(candidates,index):
    # Only fetch OHLC for symbol/date pairs needed for the next 12 index sessions.
    dates=[d for d,_ in index]
    di={v:i for i,v in enumerate(dates)}
    needed=set()
    for row in candidates:
        i=di.get(row['signal_date'])
        if i is None:continue
        for j in range(i+1,min(len(dates),i+13)):
            needed.add((dates[j],row['code']))
    db=duckdb.connect(database=':memory:')
    db.execute("SET memory_limit='500MB'")
    db.execute(f"SET temp_directory='{ROOT}/duckdb_tmp'")
    db.execute("SET threads=2")
    request=pd.DataFrame(sorted(needed),columns=['day','code'])
    request['day']=pd.to_datetime(request['day'])
    db.register('needed',request)
    sql="""SELECT CAST(p.Date AS DATE) AS day, p.Code AS code,
        p.Open AS o, p.High AS h, p.Low AS l,p.Close AS c, p.Volume AS volume,p.Stocks AS shares
        FROM read_parquet(?) p INNER JOIN needed r
        ON CAST(p.Date AS DATE)=CAST(r.day AS DATE) AND p.Code=r.code
        WHERE p.Market='KOSPI'"""
    rows=db.execute(sql,[PATS]).fetchall()
    bars={}
    for dt,code,o,h,l,c,volume,shares in rows:
        if any(v is None or v<=0 for v in (o,h,l,c)) or h<max(o,c) or l>min(o,c):
            continue
        bars[(dt.isoformat(),code)]={'o':float(o),'h':float(h),'l':float(l),'c':float(c),'v':float(volume or 0),'shares':int(shares or 0)}
    db.close()
    return bars,len(needed)

def run_variant(label,candidates,index,bars):
    dates=[d for d,_ in index if START<=d<=END]
    signals=defaultdict(list)
    for c in candidates:signals[c['signal_date']].append(c)
    entries={}
    exits={}
    for dt,_ in index:
        if dt<START:continue
        if dt>END:break
    cash=BASE_CASH
    positions={}
    events=[]
    equity_series=[]
    missing_exit=0;attempted=filled=unfilled=0;skip_slots=0
    plan_exits={}
    prev_date=None
    last_known={}
    for day in dates:
        # Exit orders scheduled at previous close; then rank fresh entry orders
        # at today's open. No exit decisions are based on today's intraday prices.
        for code in list(plan_exits):
            if code not in positions:plan_exits.pop(code,None);continue
            b=bars.get((day,code))
            if b is None:
                missing_exit+=1
                continue # wait for NEXT tradable day; never invent a fill.
            pos=positions.pop(code)
            px=b['o']
            out_slip=C_EXIT_SLIP if label=='C_conservative_limit' else 0.0005
            exit_px=px*(1-out_slip)
            proceeds=pos['qty']*exit_px*(1-sale_tax(day)-BROKER)
            cash+=proceeds
            pnl=proceeds-pos['entry_total']
            events.append({
                'code':code,'name':pos['name'],'signal_date':pos['signal_date'],
                'entry_date':pos['entry_date'],'exit_date':day,
                'entry_price':round(pos['entry_price'],4),
                'exit_price':round(exit_px,4),
                'reason':plan_exits[code],
                'pnl':round(pnl,2),'return_pct':round(pnl/pos['entry_total']*100,4),
                'days_held':pos['days'], 'variant':label,
            })
            plan_exits.pop(code,None)
        # Entry decisions based on the previous trading day's close.
        picks=sorted(signals.get(prev_date,[]),key=lambda x:(x['return5'],x['code'])) if prev_date else []
        available=max(0,MAX_POSITIONS-len(positions))
        for signal in picks:
            code=signal['code']
            if code in positions:continue
            if available<=0:
                skip_slots+=1;continue
            attempted+=1
            bar=bars.get((day,code))
            if not bar or bar['v']<=0:
                unfilled+=1;continue
            limit=signal['close']*.99
            extra_entry_buffer=0.0
            if label=='B_next_open':
                entry_px=bar['o']*1.0005
            elif label=='A_limit':
                if bar['l']>limit:
                    unfilled+=1;continue
                entry_px=min(bar['o'],limit)
            elif label=='C_conservative_limit':
                if bar['o']>limit and bar['l']>limit*(1-C_PENETRATION):
                    unfilled+=1;continue
                if bar['l']>limit and bar['o']>limit:
                    unfilled+=1;continue
                # Buy limits cannot fill ABOVE the submitted limit price.
                # Represent extra 0.1% execution uncertainty as a separate
                # budgeted cost buffer, not an invalid fill price.
                entry_px=limit if bar['o']>limit else bar['o']
                extra_entry_buffer=C_ENTRY_BUFFER
            else:raise ValueError(label)
            # position uses ~20% of current equity, not share count rounding.
            equity=cash+sum(p['qty']*last_known.get(c,p['entry_price']) for c,p in positions.items())
            budget=min(cash,ENTRY_WEIGHT*equity)
            qty=int(budget/(entry_px*(1+BROKER+extra_entry_buffer)))
            if qty<=0:
                unfilled+=1;continue
            total=qty*entry_px*(1+BROKER+extra_entry_buffer)
            cash-=total
            positions[code]={
                'code':code,'name':signal['name'],'signal_date':signal['signal_date'],
                'entry_date':day,'qty':qty,'entry_total':total,'entry_price':entry_px,
                'history':list(signal['prior_closes']),'days':0,'last_shares':None,
            }
            last_known[code]=entry_px
            filled+=1;available-=1
        # Decisions only on today's closing bar for positions. Schedule tomorrow's
        # open exit; never sell at the same close used to generate the trigger.
        for code,pos in list(positions.items()):
            bar=bars.get((day,code))
            if not bar:continue
            pos['days']+=1
            pos['history'].append(bar['c'])
            pos['history']=pos['history'][-5:]
            last_known[code]=bar['c']
            if code in plan_exits:continue
            ma5=sum(pos['history'])/len(pos['history'])
            if bar['c']>ma5:plan_exits[code]='MA5_recovery'
            elif bar['c']<=pos['entry_price']*.92:plan_exits[code]='close_below_minus8pct'
            elif pos['days']>=MAX_DAYS:plan_exits[code]='time_7_sessions'
        equity=cash+sum(pos['qty']*last_known.get(code,pos['entry_price']) for code,pos in positions.items())
        equity_series.append((day,round(equity,2)))
        prev_date=day
    return {'name':label,'events':events,'equity_series':equity_series,
            'attempted':attempted,'filled':filled,'unfilled':unfilled,
            'skipped_capacity':skip_slots,'remaining_positions':len(positions),
            'missing_exit_bars':missing_exit}

def metrics(run,index,begin,end):
    series=[(d,v) for d,v in run['equity_series'] if begin<=d<=end]
    if len(series)<2:return None
    d0,v0=series[0];dn,vn=series[-1]
    years=(datetime.fromisoformat(dn)-datetime.fromisoformat(d0)).days/365.25
    values=[e for _,e in series]
    peak=values[0];dd=0.0
    for e in values:
        peak=max(peak,e);dd=min(dd,e/peak-1)
    events=[x for x in run['events'] if begin<=x['exit_date']<=end]
    wins=[e for e in events if e['pnl']>0]
    losses=[e for e in events if e['pnl']<=0]
    gains=sum(e['pnl'] for e in wins)
    lost=-sum(e['pnl'] for e in losses)
    idx=[(d,v) for d,v in index if d0<=d<=dn]
    kospi=idx[-1][1]/idx[0][1]-1 if len(idx)>=2 else None
    return {
      'start':d0,'end':dn,'start_equity':round(v0,2),'end_equity':round(vn,2),
      'total_return_pct':round((vn/v0-1)*100,2),
      'cagr_pct':round(((vn/v0)**(1/years)-1)*100,2),
      'mdd_pct':round(dd*100,2),
      'kospi_buyhold_price_return_pct':round(kospi*100,2) if kospi is not None else None,
      'closed_trades':len(events),'win_rate_pct':round(len(wins)/len(events)*100,2) if events else None,
      'profit_factor':round(gains/lost,3) if lost>0 else None,
      'average_trade_return_pct':round(sum(e['return_pct'] for e in events)/len(events),3) if events else None,
      'average_hold_sessions':round(sum(e['days_held'] for e in events)/len(events),2) if events else None,
      'worst_trade_pct':round(min(e['return_pct'] for e in events),2) if events else None,
    }

def main():
    index,index_info=load_index()
    print('INDEX',len(index),index[0],index[-1],flush=True)
    signals,stats=collect_signals(index_info)
    print('SIGNALS',len(signals),'STATS',stats,flush=True)
    paths=sorted(DATA.glob('marcap-*.parquet'))
    hashes={p.name:sha256(p) for p in paths}
    with (RESULT/'signals.csv').open('w',newline='',encoding='utf-8-sig') as f:
        if signals:
            w=csv.DictWriter(f,fieldnames=[k for k in signals[0] if k!='prior_closes'])
            w.writeheader()
            for x in signals:w.writerow({k:x[k] for k in w.fieldnames})
    if not signals:
        print('NO_SIGNALS, ABORT PORTFOLIO');return
    bars,demanded=load_future_bars(signals,index)
    print('BAR_LOOKUPS',demanded,'FOUND',len(bars),flush=True)
    # Immutable fixture *derived from real data*: rerun alternative fee/cost
    # policies without repeated web downloads or touching any live engine.
    snapshot={'signals':signals,'bars':[[dt,code,data] for (dt,code),data in bars.items()]}
    with gzip.open(RESULT/'research_snapshot.json.gz','wt',encoding='utf-8') as f:
        json.dump(snapshot,f,ensure_ascii=False,separators=(',',':'))
    runs=[run_variant(x,signals,index,bars) for x in ['A_limit','B_next_open','C_conservative_limit']]
    summary={'strategy':'KOSPI large-cap RSI(2) oversold reversal','source':'real historic: FinanceData marcap annual parquet + Naver Finance KOSPI index',
         'fixture_backed':False,'orders_executed':False,'notes':[
         'Point-in-time top 150 market cap KOSPI ordinary stocks, average 20-session turnover >= KRW 10b',
         'Close > MA200 for both KOSPI and stock, 5-session return <= -7%, Wilder RSI2 < 10',
         'Orders generated after close, next open entry or limit; close-condition exits next available open',
         'No reinvestment of dividends, no corporate-action adjusted OHLC; split-era 200-session signal quarantine',
         'Conservative limit requires 0.2% low-price penetration, plus 0.1% separate entry cost buffer; never execute above the limit',
         'Sell tax calendar: 0.30% to 2019-06-02, 0.25% to 2020-12-31, 0.23% to 2022, 0.20% 2023, 0.18% 2024, 0.15% 2025, 0.20% 2026',
         'No full auction/queue simulation, tick size, market impact, historical delisting proceeds or suspension event reconstruction',
         'Backtest is diagnostic, not promotion quality or a profitability guarantee'
        ],
         'data_provenance':{'index_sha256':sha256(DATA/'kospi-index-naver-2014-2026.txt'),'annual_marcap_sha256':hashes},
         'strategy_params':{'market':'KOSPI','top_n':TOP_N,'avg_trade_value_KRW':TURNOVER,'max_stocks':MAX_POSITIONS,
             'entry_weight':ENTRY_WEIGHT,'brokerage_per_side':BROKER,'sale_tax_calendar':TAX_POLICY,
             'max_hold_trading_sessions':MAX_DAYS},
         'signal_data_stats':stats,'signals_total':len(signals),
         'bars_requested':demanded,'bars_found':len(bars),'variants':{}}
    for run in runs:
        label=run['name']
        summary['variants'][label]={
          'overall':metrics(run,index,START,END),
          'train_2015_2021':metrics(run,index,'2015-01-02','2021-12-30'),
          'test_2022_2026':metrics(run,index,'2022-01-03',END),
          'calendar_years':{str(y):metrics(run,index,f'{y}-01-01',f'{y}-12-31') for y in range(2015,2027)},
          'attempted_buy_orders':run['attempted'],'filled_buy_orders':run['filled'],
          'unfilled_or_missing_buy_orders':run['unfilled'],
          'capacity_skipped_candidates':run['skipped_capacity'],
          'missing_scheduled_exit_bars':run['missing_exit_bars'],
          'positions_open_at_end':run['remaining_positions'],
        }
        with (RESULT/f'trades_{label}.csv').open('w',newline='',encoding='utf-8-sig') as f:
            if run['events']:
                w=csv.DictWriter(f,fieldnames=run['events'][0].keys());w.writeheader();w.writerows(run['events'])
        with (RESULT/f'equity_{label}.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.writer(f);w.writerow(['date','equity_KRW']);w.writerows(run['equity_series'])
        print('VARIANT',label,summary['variants'][label]['overall'],flush=True)
        print('TRAIN',summary['variants'][label]['train_2015_2021'],flush=True)
        print('TEST',summary['variants'][label]['test_2022_2026'],flush=True)
    (RESULT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print('RESULT_READY',RESULT/'summary.json')

if __name__=='__main__':
    main()

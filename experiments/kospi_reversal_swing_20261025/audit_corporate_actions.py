"""Read-only per-position corporate-action / price-gap audit on real OHLC."""
from pathlib import Path
import duckdb, pandas as pd, json
root=Path(__file__).resolve().parent
db=duckdb.connect()
db.execute("SET threads=2")
db.execute("SET memory_limit='450MB'")
df=pd.read_csv(root/'results/trades_C_conservative_limit.csv',dtype={'code':str})
df['code']=df.code.str.zfill(6)
for c in ('entry_date','exit_date'):df[c]=pd.to_datetime(df[c])
df['trade_id']=range(len(df))
db.register('trades',df)
p=str(root/'data/marcap-*.parquet')
sql=f"""SELECT t.trade_id,p.Code,p.Date,p.Close,p.Stocks,p.Open,
 t.name, t.entry_date,t.exit_date,t.return_pct
 FROM read_parquet('{p}') p
 JOIN trades t ON p.Code=t.code AND p.Date >=t.entry_date AND p.Date<=t.exit_date
 WHERE p.Market='KOSPI'
 ORDER BY t.trade_id,p.Date"""
rows=db.execute(sql).fetchall()
flags=[];pos={}
for id,code,dt,c,shares,o,name,ent,ex,pct in rows:
 prev=pos.get(id)
 if prev:
  date0, c0, shares0=prev
  chgshares=(shares/shares0) if shares and shares0 else 1
  chgprice=(c/c0) if c and c0 else 1
  suspect=(chgshares>1.25 or chgshares<.8 or chgprice>1.5 or chgprice<.6)
  if suspect:
   flags.append({'trade_id':id,'code':code,'name':name,'date':dt.isoformat(),'share_ratio':round(chgshares,4),'price_ratio':round(chgprice,4),'trade_return_pct':round(float(pct),3),'held_from':ent.isoformat(),'held_to':ex.isoformat()})
 pos[id]=(dt,c,shares)
print('total_completed_trades',len(df),'observed_bar_records',len(rows),'flagged_split_or_large_jump',len(flags))
for f in flags[:30]:print(f)
(root/'results/corporate_action_audit.json').write_text(json.dumps({'trade_count':len(df),'bars_joined':len(rows),'anomalies':flags},ensure_ascii=False,indent=2))

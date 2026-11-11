"""Fixed position-size risk sensitivity and nonparametric confidence diagnostics."""
import gzip,json
from pathlib import Path
import numpy as np
import pandas as pd
import kospi_reversal_research as r
root=Path(__file__).resolve().parent
with gzip.open(root/'results/research_snapshot.json.gz','rt',encoding='utf-8') as f:
    d=json.load(f)
bars={(date,symbol):row for date,symbol,row in d['bars']}
signals=d['signals']
index,_=r.load_index()
r.TAX_POLICY='historical'
r.TICK_POLICY='historical'
r.C_PENETRATION=.002
r.C_ENTRY_BUFFER=.001
r.C_EXIT_SLIP=.001
scenarios=[
    ('five_20pct',5,.20),
    ('five_10pct',5,.10),
    ('three_10pct',3,.10),
]
results={}
for name,max_positions,weight in scenarios:
    r.MAX_POSITIONS=max_positions;r.ENTRY_WEIGHT=weight
    x=r.run_variant('C_conservative_limit',signals,index,bars)
    result={'overall':r.metrics(x,index,r.START,r.END),
            'oos':r.metrics(x,index,'2022-01-03',r.END),
            'train':r.metrics(x,index,'2015-01-02','2021-12-30'),
            'max_positions':max_positions,'entry_weight':weight}
    results[name]=result
    o=result['oos']
    print(name,'oos_total',o['total_return_pct'],'CAGR',o['cagr_pct'],'MDD',o['mdd_pct'],
          'PF',o['profit_factor'],'active_sessions',o['active_sessions_pct'],
          'avg_invested',o['average_invested_pct'],flush=True)
    if name=='five_20pct':
        v=pd.DataFrame(x['equity_series'],columns=['date','equity'])
        v=v[v.date.between('2022-01-03','2026-10-23')].copy()
        v['month']=pd.to_datetime(v.date).dt.to_period('M')
        monthly=v.groupby('month').equity.last().pct_change().dropna()
        returns=monthly.to_numpy()
        # Overlapping stationary BLOCK bootstrap by 3-month windows to
        # approximately preserve serial clustering of strategy gains/losses.
        rng=np.random.default_rng(20261025)
        months=len(returns)
        paths=10000
        simulations=np.empty(paths)
        for i in range(paths):
            resampled=[]
            while len(resampled)<months:
                s=int(rng.integers(0,months))
                resampled.extend(returns[(s+j)%months] for j in range(3))
            simulations[i]=float(np.prod(1+np.asarray(resampled[:months]))-1)
        results[name]['monthly_block_bootstrap']={
            'observed_months':months,'block_length_months':3,'replicates':paths,
            'resampled_total_return_pct_p05':round(float(np.percentile(simulations,5))*100,2),
            'resampled_total_return_pct_p50':round(float(np.percentile(simulations,50))*100,2),
            'resampled_total_return_pct_p95':round(float(np.percentile(simulations,95))*100,2),
            'resampled_loss_probability_pct':round(float((simulations<0).mean())*100,2),
            'interpretation':'Exploratory resampling of in-period monthly returns, NOT prospective win probability',
        }
print('BOOTSTRAP',results['five_20pct']['monthly_block_bootstrap'],flush=True)
(root/'results/risk_sensitivity.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))

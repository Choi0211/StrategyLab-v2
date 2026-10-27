"""Read-only execution quality stress: actual KRX legal price increments."""
import gzip,json
from pathlib import Path
import kospi_reversal_research as r
root=Path(__file__).resolve().parent
with gzip.open(root/'results/research_snapshot.json.gz','rt',encoding='utf-8') as f:
    x=json.load(f)
bars={(d,c):v for d,c,v in x['bars']}
signals=x['signals']
idx,_=r.load_index()
results={}
scenarios=[
 ('A_original_fractional_limit','A_limit','off',.002,.001,.001),
 ('A_historical_KRX_ticks','A_limit','historical',.002,.001,.001),
 ('C_original_fractional_limit','C_conservative_limit','off',.002,.001,.001),
 ('C_historical_KRX_ticks','C_conservative_limit','historical',.002,.001,.001),
 ('C_KRX_ticks_penetration_05pct','C_conservative_limit','historical',.005,.001,.001),
 ('C_KRX_ticks_penetration_10pct','C_conservative_limit','historical',.01,.001,.001),
 ('C_KRX_ticks_friction_03pct','C_conservative_limit','historical',.002,.003,.003),
]
for title,mode,tick,penetration,entry_cost,exit_slip in scenarios:
    r.TAX_POLICY='historical'
    r.TICK_POLICY=tick
    r.C_PENETRATION=penetration
    r.C_ENTRY_BUFFER=entry_cost
    r.C_EXIT_SLIP=exit_slip
    v=r.run_variant(mode,signals,idx,bars)
    result={'tick_rule':tick,'mode':mode,'penetration':penetration,
            'entry_cost':entry_cost,'exit_slip':exit_slip,
            'full':r.metrics(v,idx,r.START,r.END),
            'test_2022_2026':r.metrics(v,idx,'2022-01-03',r.END),
            'filled_orders':v['filled'],'attempted_orders':v['attempted'],
            'missing_exit_bars':v['missing_exit_bars']}
    results[title]=result
    oos=result['test_2022_2026']
    print(title, 'oos_return',oos['total_return_pct'],'cagr',oos['cagr_pct'],
          'mdd',oos['mdd_pct'],'pf',oos['profit_factor'],
          'trades',oos['closed_trades'],'filled_all',v['filled'],flush=True)
    if title=='C_historical_KRX_ticks':
        # preserve adjusted reference trades for cross-validation.
        import csv
        with (root/'results/trades_C_KRX_ticks.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=v['events'][0].keys())
            w.writeheader();w.writerows(v['events'])
        with (root/'results/equity_C_KRX_ticks.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.writer(f);w.writerow(['date','equity_KRW']);w.writerows(v['equity_series'])
(root/'results/tick_stress.json').write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8')

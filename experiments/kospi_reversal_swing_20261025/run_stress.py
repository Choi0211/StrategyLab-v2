"""Fixed, ex-ante scenario stress tests on saved REAL-DATA observations."""
import gzip, json, pathlib
import kospi_reversal_research as r
import statistics

root=pathlib.Path(__file__).resolve().parent
with gzip.open(root/'results/research_snapshot.json.gz','rt',encoding='utf-8') as f:
    x=json.load(f)
bars={(d,c):v for d,c,v in x['bars']}
signals=x['signals']
index,_=r.load_index()
cases={
  'baseline_historical': {'policy':'historical','penetration':.002,'entry_buffer':.001,'exit_slip':.001},
  'all_years_tax_035': {'policy':'flat35','penetration':.002,'entry_buffer':.001,'exit_slip':.001},
  'deep_penetration_050pct': {'policy':'historical','penetration':.005,'entry_buffer':.001,'exit_slip':.001},
  'deep_penetration_100pct': {'policy':'historical','penetration':.01,'entry_buffer':.001,'exit_slip':.001},
  'higher_friction_030pct_side':{'policy':'historical','penetration':.002,'entry_buffer':.003,'exit_slip':.003},
}
result={}
for title,cfg in cases.items():
    r.TAX_POLICY=cfg['policy'];r.C_PENETRATION=cfg['penetration'];r.C_ENTRY_BUFFER=cfg['entry_buffer'];r.C_EXIT_SLIP=cfg['exit_slip']
    run=r.run_variant('C_conservative_limit',signals,index,bars)
    result[title]={
      'parameters':cfg,'overall':r.metrics(run,index,r.START,r.END),
      'train':r.metrics(run,index,'2015-01-02','2021-12-30'),
      'oos':r.metrics(run,index,'2022-01-03',r.END),
      'orders_attempted':run['attempted'],'orders_filled':run['filled'],
    }
    x=result[title]['oos']
    print(title, 'OOS_return_pct',x['total_return_pct'],'OOS_cagr_pct',x['cagr_pct'],
          'OOS_MDD',x['mdd_pct'],'OOS_PF',x['profit_factor'],
          'OOS_trades',x['closed_trades'])
(root/'results/stress.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))

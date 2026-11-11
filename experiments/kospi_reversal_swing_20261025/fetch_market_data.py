"""Manually fetch historical public Korean market datasets for offline research."""
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.parse import urlencode
import hashlib

root=Path(__file__).resolve().parent
data=root/'data'
data.mkdir(exist_ok=True)
for year in range(2014,2027):
    p=data/f'marcap-{year}.parquet'
    if p.exists() and p.stat().st_size>8_000_000:
        continue
    url=f'https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{year}.parquet'
    with urlopen(Request(url,headers={'User-Agent':'Gaon offline research'}),timeout=90) as r:
        raw=r.read(50_000_000)
    if not 8_000_000<len(raw)<50_000_000:
        raise ValueError(f'Unexpected data size for {year}')
    tmp=p.with_suffix('.part');tmp.write_bytes(raw);tmp.replace(p)
    print(year,len(raw),hashlib.sha256(raw).hexdigest())
p=data/'kospi-index-naver-2014-2026.txt'
if not p.exists():
    qs=urlencode({'symbol':'KOSPI','requestType':'1','startTime':'20140101','endTime':'20261025','timeframe':'day'})
    req=Request('https://api.finance.naver.com/siseJson.naver?'+qs,
                headers={'User-Agent':'Mozilla/5.0','Referer':'https://finance.naver.com/'})
    with urlopen(req,timeout=45) as r:raw=r.read(2_000_000)
    if b'20140102' not in raw or b'20261023' not in raw:
        raise ValueError('KOSPI index coverage mismatch')
    p.write_bytes(raw)
    print('INDEX',len(raw),hashlib.sha256(raw).hexdigest())
print('Compare dataset SHA-256 with the pinned values in results/summary.json.')

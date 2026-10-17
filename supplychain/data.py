"""Contracts and independent synthetic fixtures. No private inputs are read here."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8', newline='\n')

def generate_demo(directory, seed=20261017, n_skus=48, n_days=420):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    rng=np.random.default_rng(seed)
    dates=pd.date_range('2024-01-01',periods=n_days)
    rows=[];products=[];annual=[]
    for i in range(n_skus):
        sku=f'SKU_{i+1:03}'; group=i%4
        mean=float(rng.uniform(5,45)); slope=float(rng.uniform(-0.001,0.0015))
        t=np.arange(n_days)
        weekly=1+0.23*np.sin(2*np.pi*t/7+i/3)
        # Authored seasonal scenarios, not a transformation of any private series.
        seasonal=1+0.6*np.exp(-((t%365-220)/40)**2)
        rate=np.maximum(0.1,mean*np.exp(slope*t)*weekly*seasonal)
        demand=rng.negative_binomial(12,12/(12+rate)).astype(float)
        regime=['regular','trending','intermittent','lumpy'][group]
        if group==1: demand=np.rint(demand*(0.6+0.8*t/max(n_days-1,1)))
        if group==2: demand*=rng.binomial(1,0.24,n_days)
        if group==3: demand*=rng.binomial(1,0.12,n_days)*rng.integers(2,6,n_days)
        rows.extend({'date':str(day.date()),'sku':sku,'demand':int(q)} for day,q in zip(dates,demand))
        products.append({'sku':sku,'family':f'GROUP_{i%6+1:02}', 'regime':regime,
            'lead_time_days':int(rng.integers(3,10)), 'batch_size':int(rng.choice([5,10,20])),
            'unit_cost':round(float(rng.uniform(1,4)),2)})
    for i in range(72):
        base=float(rng.uniform(200,2000)); trend=float(rng.uniform(0.78,1.12))
        for year in range(2020,2025):
            sales=max(0,int(base*trend**(year-2020)*rng.lognormal(-0.02,0.2)))
            annual.append({'sku':f'PRINT_{i+1:03}','year':year,'sales':sales,
                'shipments':int(sales*rng.uniform(1.1,1.6)),'family':f'GROUP_{i%2+1:02}'})
    for name,frame in [('daily',pd.DataFrame(rows)),('products',pd.DataFrame(products)),('annual',pd.DataFrame(annual))]:
        frame.to_csv(directory/f'{name}.csv',index=False,lineterminator='\n')
    write_json(directory/'manifest.json',{'mode':'independent_synthetic','seed':seed,
        'n_skus':n_skus,'n_days':n_days,'generator':'supplychain.data.generate_demo',
        'private_inputs_read':False,'operational_parameters':'authored scenario assumptions',
        'sha256':{n:sha256(directory/n) for n in ['daily.csv','products.csv','annual.csv']}})

def load_daily(path):
    data=pd.read_csv(path, dtype={'sku':str})
    required={'date','sku','demand'}
    if not required.issubset(data): raise ValueError(f'Missing columns: {required-set(data)}')
    if data[list(required)].isna().any().any(): raise ValueError('Null daily keys or demand')
    if data.sku.str.strip().eq('').any(): raise ValueError('Blank SKU')
    data['date']=pd.to_datetime(data.date,errors='raise')
    if not data.date.dt.normalize().eq(data.date).all(): raise ValueError('Expected daily midnight dates')
    if data.duplicated(['date','sku']).any(): raise ValueError('Duplicate date/SKU keys')
    data['demand']=pd.to_numeric(data.demand,errors='raise')
    if not np.isfinite(data.demand).all() or (data.demand<0).any(): raise ValueError('Demand must be finite and nonnegative')
    panel=data.pivot(index='date',columns='sku',values='demand').sort_index()
    calendar=pd.date_range(panel.index.min(),panel.index.max())
    if not panel.index.equals(calendar) or panel.isna().any().any():
        raise ValueError('Incomplete panel: resolve ingestion gaps before explicitly filling valid zero-sales dates')
    return panel

def load_annual(path):
    data=pd.read_csv(path,dtype={'sku':str})
    if not {'sku','year','sales','shipments','family'}.issubset(data): raise ValueError('Annual schema mismatch')
    if data.duplicated(['sku','year']).any(): raise ValueError('Duplicate annual SKU/year keys')
    if data[['sku','year','sales','shipments','family']].isna().any().any(): raise ValueError('Null annual values')
    if not np.isfinite(data[['year','sales','shipments']]).all().all(): raise ValueError('Nonfinite annual values')
    if (data[['sales','shipments']]<0).any().any(): raise ValueError('Negative annual quantities')
    if not np.equal(data.year,np.floor(data.year)).all(): raise ValueError('Year must be an integer')
    panel=data.pivot(index='year',columns='sku',values='sales').sort_index()
    if panel.isna().any().any() or not np.all(np.diff(panel.index)==1): raise ValueError('Annual panel has gaps')
    return data,panel

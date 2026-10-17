"""ABC/XYZ review policies and a lost-sales simulator with explicit event order."""
import math
import numpy as np
import pandas as pd
from scipy.stats import norm
from .forecast import predict

POLICIES=('uniform_95','segmented_forecast','fixed_cover')

def segment(history,products):
    products=products.set_index('sku').loc[history.columns]
    value=history.sum()*products.unit_cost
    total=float(value.sum())
    previous=(value.sort_values(ascending=False,kind='stable').cumsum()-value.sort_values(ascending=False,kind='stable'))/total if total else value*0
    abc={sku:('C' if total==0 else 'A' if v<0.8 else 'B' if v<0.95 else 'C') for sku,v in previous.items()}
    rows=[]
    for sku in history:
        mean=float(history[sku].mean());sd=float(history[sku].std(ddof=0))
        cv=sd/mean if mean>0 else None
        rows.append({'sku':sku,'abc':abc[sku],'xyz':'Z' if cv is None or cv>1 else 'Y' if cv>0.5 else 'X',
            'cv':cv,'history_units':float(history[sku].sum()),'scenario_consumption_value':float(value[sku])})
    return pd.DataFrame(rows)

def validate_products(products,skus):
    required={'sku','lead_time_days','batch_size','unit_cost'}
    if not required.issubset(products): raise ValueError('Product parameters missing')
    if products.sku.duplicated().any(): raise ValueError('Duplicate product SKU')
    if set(products.sku)!=set(skus): raise ValueError('Product keys differ from daily panel')
    numeric=products[['lead_time_days','batch_size','unit_cost']]
    if not np.isfinite(numeric).all().all() or (numeric<=0).any().any(): raise ValueError('Invalid product parameters')
    if not np.equal(products.lead_time_days,np.floor(products.lead_time_days)).all(): raise ValueError('Lead time must be integer days')
    if not np.equal(products.batch_size,np.floor(products.batch_size)).all(): raise ValueError('Batch size must be integer')

def simulate(panel,products,selected,cutoff,lead_factor=1.0,keep_trace=True):
    validate_products(products,panel.columns)
    classes=segment(panel.iloc[:cutoff],products).set_index('sku')
    params=products.set_index('sku');traces=[];summaries=[]
    for policy in POLICIES:
        for sku in panel:
            p=params.loc[sku];y=panel[sku].to_numpy();lead=max(1,round(p.lead_time_days*lead_factor))
            review=7;batch=int(p.batch_size);cost=float(p.unit_cost)
            initial=math.ceil(y[max(0,cutoff-28):cutoff].mean()*(lead+review))
            onhand=float(initial);pipeline=[];holding=0.;lost_total=0.;ordered_total=0.;orders=0;filled_total=0.
            for t in range(cutoff,len(y)):
                # Start-of-day receipts -> demand -> end-of-day review; no future actuals are used.
                received=sum(q for arrival,q in pipeline if arrival==t)
                pipeline=[(arrival,q) for arrival,q in pipeline if arrival>t]
                begin=onhand+received;filled=min(begin,y[t]);lost=y[t]-filled;onhand=begin-filled
                holding+=onhand*cost*0.001;lost_total+=lost;filled_total+=filled
                ordered=0
                if (t-cutoff)%review==0:
                    hist=y[:t+1];protection=lead+review;mean=float(hist[-28:].mean());sd=float(hist[-56:].std())
                    if policy=='segmented_forecast':
                        service={'A':0.98,'B':0.95,'C':0.90}[classes.loc[sku,'abc']]
                        target=float(predict(hist,protection,selected[sku]).sum())+norm.ppf(service)*sd*np.sqrt(protection)
                    elif policy=='uniform_95': target=mean*protection+norm.ppf(0.95)*sd*np.sqrt(protection)
                    else: target=mean*(protection+7)
                    position=onhand+sum(q for _,q in pipeline)
                    ordered=math.ceil(max(0,target-position)/batch)*batch
                    if ordered: pipeline.append((t+lead,float(ordered)));ordered_total+=ordered;orders+=1
                if keep_trace:
                    traces.append({'policy':policy,'sku':sku,'date':str(panel.index[t].date()),
                        'initial_on_hand':initial,'received':received,'demand':float(y[t]),'filled':float(filled),
                        'lost':float(lost),'end_on_hand':onhand,'ordered':ordered,
                        'in_transit':sum(q for _,q in pipeline),'lead_time_days':lead})
            total=float(y[cutoff:].sum())
            summaries.append({'policy':policy,'sku':sku,'lead_factor':lead_factor,
                'demand':total,'filled':filled_total,'lost':lost_total,
                'fill_rate':filled_total/total if total else None,'holding_cost':holding,
                'lost_cost_base':lost_total*cost,'orders':orders,'ordering_cost':orders*5.0,
                'initial_stock':initial,'ending_stock':onhand,'ending_pipeline':sum(q for _,q in pipeline),
                'ordered_units':ordered_total,'scenario_unit_cost':cost})
    return classes.reset_index(),pd.DataFrame(summaries),pd.DataFrame(traces)

def aggregate_results(detail,shortage_multiplier=5.0):
    rows=[]
    for policy,g in detail.groupby('policy'):
        demand=float(g.demand.sum());cost=float(g.holding_cost.sum()+g.ordering_cost.sum()+shortage_multiplier*g.lost_cost_base.sum())
        rows.append({'policy':policy,'lead_factor':float(g.lead_factor.iloc[0]),
            'shortage_multiplier':shortage_multiplier,'fill_rate':float(g.filled.sum()/demand) if demand else None,
            'service_cost':cost,'holding_cost':float(g.holding_cost.sum()),'orders':int(g.orders.sum()),
            'lost_units':float(g.lost.sum()),'ending_stock':float(g.ending_stock.sum()),
            'ending_pipeline':float(g.ending_pipeline.sum())})
    return pd.DataFrame(rows)

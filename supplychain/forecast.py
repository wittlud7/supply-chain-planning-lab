"""Fixed, transparent baselines with chronological model selection."""
import numpy as np
import pandas as pd

MODELS=('seasonal_naive','mean_28','ses','croston_sba','weekday_blend')

def predict(history,horizon,model):
    y=np.asarray(history,dtype=float)
    if not len(y) or horizon<1: raise ValueError('History and positive horizon are required')
    if not np.isfinite(y).all() or (y<0).any(): raise ValueError('Invalid history')
    if model=='seasonal_naive': out=np.resize(y[-min(7,len(y)):],horizon)
    elif model=='mean_28': out=np.full(horizon,y[-28:].mean())
    elif model=='ses':
        level=y[0]
        for value in y[1:]: level=0.25*value+0.75*level
        out=np.full(horizon,level)
    elif model=='croston_sba':
        positions=np.flatnonzero(y>0)
        if not len(positions): return np.zeros(horizon)
        alpha=0.1; first=positions[0]; size=y[first]; interval=float(first+1); last=first
        for pos in positions[1:]:
            size=alpha*y[pos]+(1-alpha)*size
            interval=alpha*(pos-last)+(1-alpha)*interval;last=pos
        out=np.full(horizon,(1-alpha/2)*size/interval)
    elif model=='weekday_blend':
        recent=y[-28:]; start=len(y)-len(recent)
        weekday=np.array([recent[(np.arange(start,len(y))%7)==j].mean()
                          if ((np.arange(start,len(y))%7)==j).any() else recent.mean() for j in range(7)])
        ratio=np.clip(y[-7:].mean()/max(y[-28:].mean(),1e-9),0.5,1.5)
        out=0.7*weekday[np.arange(len(y),len(y)+horizon)%7]*ratio+0.3*y[-7:].mean()
    else: raise ValueError(f'Unknown model: {model}')
    return np.maximum(out,0)

def select_models(panel,cutoff,validation_days=42,horizon=7):
    if cutoff-validation_days<56: raise ValueError('Insufficient pre-validation history')
    selected={};rows=[]
    for sku in panel:
        y=panel[sku].to_numpy();scores={m:0.0 for m in MODELS}
        for origin in range(cutoff-validation_days,cutoff-horizon+1,horizon):
            actual=y[origin:origin+horizon]
            for model in MODELS: scores[model]+=float(np.abs(actual-predict(y[:origin],horizon,model)).sum())
        selected[sku]=min(MODELS,key=lambda m:scores[m])
        rows.extend({'sku':sku,'model':m,'validation_absolute_error':v,'selected':m==selected[sku],
                     'selection_end':str(panel.index[cutoff-1].date())} for m,v in scores.items())
    return selected,pd.DataFrame(rows)

def evaluate(panel,holdout_days=56,horizon=7):
    if holdout_days%horizon: raise ValueError('Holdout must contain complete nonoverlapping forecast blocks')
    cutoff=len(panel)-holdout_days
    selected,selection=select_models(panel,cutoff,horizon=horizon)
    rows=[]
    for sku in panel:
        y=panel[sku].to_numpy()
        for origin in range(cutoff,len(panel),horizon):
            hist=y[:origin];actual=y[origin:origin+horizon]
            scale=np.abs(hist[7:]-hist[:-7]).mean()
            for model in (*MODELS,'selected'):
                underlying=selected[sku] if model=='selected' else model
                forecast=predict(hist,len(actual),underlying)
                for step,(a,f) in enumerate(zip(actual,forecast)):
                    rows.append({'sku':sku,'origin':str(panel.index[origin].date()),
                        'train_end':str(panel.index[origin-1].date()),'date':str(panel.index[origin+step].date()),
                        'horizon_day':step+1,'model':model,'underlying_model':underlying,
                        'actual':float(a),'forecast':float(f),'absolute_error':float(abs(a-f)),
                        'scaled_absolute_error':float(abs(a-f)/scale) if scale>0 else np.nan})
    predictions=pd.DataFrame(rows);summary=[]
    for model,group in predictions.groupby('model',sort=False):
        total=group.actual.sum()
        summary.append({'model':model,'wape':float(group.absolute_error.sum()/total) if total>0 else None,
            'bias':float((group.forecast.sum()-total)/total) if total>0 else None,
            'mae':float(group.absolute_error.mean()),
            'mase':float(group.scaled_absolute_error.mean()) if group.scaled_absolute_error.notna().any() else None,
            'actual_total':float(total),'observations':len(group),
            'mase_observations':int(group.scaled_absolute_error.notna().sum())})
    return selected,selection,predictions,pd.DataFrame(summary),cutoff

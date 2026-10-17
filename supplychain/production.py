"""Annual demand/print experiments and a capacity-constrained integer lot plan."""
import math
import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp

def annual_forecast(history):
    y=np.asarray(history,dtype=float)
    if len(y)<2 or not np.isfinite(y).all() or (y<0).any(): raise ValueError('Invalid annual history')
    # A short annual series cannot identify a complex seasonal model.
    recent=y[-1];smooth=float(np.average(y[-3:],weights=np.arange(1,min(3,len(y))+1)))
    ratio=float(np.clip((y[-1]+1)/(y[-2]+1),0.7,1.15))
    return max(0.,0.5*recent*ratio+0.5*smooth)

def annual_backtest(panel):
    rows=[];residuals=[]
    # One strictly earlier origin calibrates each evaluated origin; pooled residuals
    # use normalized ratios so large SKUs do not dominate the safety factor.
    for origin in range(3,len(panel)):
        calibration=[]
        for sku in panel:
            y=panel[sku].to_numpy()
            for earlier in range(2,origin):
                pred=annual_forecast(y[:earlier])
                calibration.append(y[earlier]/max(pred,1.0))
        for shortage_cost,overage_cost in [(1.,1.),(3.,1.),(9.,1.)]:
            fractile=shortage_cost/(shortage_cost+overage_cost)
            factor=float(np.quantile(calibration,fractile,method='higher'))
            for sku in panel:
                y=panel[sku].to_numpy();prediction=annual_forecast(y[:origin]);actual=float(y[origin])
                for policy,quantity in [('last_year',y[origin-1]),('trend_blend',prediction),('pooled_newsvendor',prediction*factor)]:
                    q=math.ceil(quantity/50)*50
                    over=float(max(q-actual,0));under=float(max(actual-q,0))
                    rows.append({'sku':sku,'year':int(panel.index[origin]),'policy':policy,
                        'train_end_year':int(panel.index[origin-1]),'calibration_latest_year':int(panel.index[origin-1]),
                        'critical_fractile':fractile,'scenario_shortage_cost':shortage_cost,
                        'scenario_overage_cost':overage_cost,'forecast':prediction,'print_qty':q,'actual':actual,
                        'overage':over,'underage':under,'scenario_loss':over*overage_cost+under*shortage_cost})
        residuals.extend(calibration)
    if not rows: raise ValueError('At least four consecutive annual observations are required')
    detail=pd.DataFrame(rows)
    summary=detail.groupby(['policy','critical_fractile'],as_index=False).agg(
        scenario_loss=('scenario_loss','sum'),overage=('overage','sum'),underage=('underage','sum'),
        sku_years=('sku','size'))
    return detail,summary

def solve_lots(demand,capacity,batch_size=50,minimum_batches=2,holding_cost=1.0,shortage_cost=None,setup_cost=30.0):
    """One period: batches b (integer), setups z (binary), under/over quantities.

    min holding*over + shortage*under + setup*z
    s.t. batch*b + under - over = target; min*z <= b <= M*z;
         sum(batch*b) <= capacity. Target is net of compatible usable stock.
    """
    targets=np.asarray(demand,dtype=float);n=len(targets)
    penalties=np.ones(n)*5 if shortage_cost is None else np.asarray(shortage_cost,dtype=float)
    if n==0 or not np.isfinite(targets).all() or (targets<0).any(): raise ValueError('Invalid production targets')
    if not np.isfinite(capacity) or capacity<0 or batch_size<=0 or minimum_batches<1: raise ValueError('Invalid production constraints')
    if batch_size!=int(batch_size) or minimum_batches!=int(minimum_batches): raise ValueError('Integer lot constraints required')
    if len(penalties)!=n or not np.isfinite(penalties).all() or (penalties<=0).any() or holding_cost<0 or setup_cost<0:
        raise ValueError('Invalid cost parameters')
    max_batches=int(capacity//batch_size)
    c=np.r_[np.zeros(n),np.ones(n)*setup_cost,penalties,np.ones(n)*holding_cost]
    upper=np.r_[np.ones(n)*max_batches,np.ones(n),np.ones(2*n)*np.inf]
    integ=np.r_[np.ones(2*n),np.zeros(2*n)]
    matrix=[];lower=[];rhs=[]
    for i in range(n):
        row=np.zeros(4*n);row[i]=batch_size;row[2*n+i]=1;row[3*n+i]=-1
        matrix.append(row);lower.append(targets[i]);rhs.append(targets[i])
        row=np.zeros(4*n);row[i]=1;row[n+i]=-max_batches
        matrix.append(row);lower.append(-np.inf);rhs.append(0)
        row=np.zeros(4*n);row[i]=-1;row[n+i]=minimum_batches
        matrix.append(row);lower.append(-np.inf);rhs.append(0)
    row=np.zeros(4*n);row[:n]=batch_size;matrix.append(row);lower.append(-np.inf);rhs.append(capacity)
    result=milp(c,integrality=integ,bounds=Bounds(np.zeros(4*n),upper),
        constraints=LinearConstraint(np.array(matrix),lower,rhs),options={'time_limit':30.,'mip_rel_gap':1e-8})
    if not result.success: raise RuntimeError(f'MILP failed or unproven optimum: status={result.status}, {result.message}')
    quantities=np.rint(result.x[:n]).astype(int)*batch_size
    if quantities.sum()>capacity+1e-7 or np.any((quantities>0)&(quantities<batch_size*minimum_batches)):
        raise RuntimeError('Returned plan violates lot or capacity constraints')
    loss=float(np.maximum(targets-quantities,0)@penalties+np.maximum(quantities-targets,0).sum()*holding_cost+(quantities>0).sum()*setup_cost)
    return quantities,{'status':int(result.status),'objective':loss,'mip_gap':float(result.mip_gap),
        'dual_bound':float(result.mip_dual_bound),'capacity':float(capacity),'utilization':float(quantities.sum()/capacity) if capacity else 0.}

def greedy_lots(targets,capacity,penalties,batch_size=50,minimum_batches=2,holding_cost=1.,setup_cost=30.):
    # A feasible, intentionally simple priority heuristic: complete highest-penalty
    # jobs first, adding a lot only when its marginal savings exceeds its cost.
    targets=np.asarray(targets);penalties=np.asarray(penalties);q=np.zeros(len(targets),dtype=int)
    remain=int(capacity//batch_size)*batch_size
    for i in np.argsort(-penalties,kind='stable'):
        first=batch_size*minimum_batches
        if first>remain: continue
        def job_loss(quantity): return max(targets[i]-quantity,0)*penalties[i]+max(quantity-targets[i],0)*holding_cost+(setup_cost if quantity else 0)
        if job_loss(first)>=job_loss(0): continue
        q[i]=first;remain-=first
        while remain>=batch_size and job_loss(q[i]+batch_size)<job_loss(q[i]): q[i]+=batch_size;remain-=batch_size
    return q

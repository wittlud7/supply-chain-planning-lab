"""Run the same experiment code on independently generated or private normalized data."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from .data import load_daily,load_annual,write_json,sha256
from .forecast import evaluate
from .inventory import simulate,aggregate_results
from .production import annual_backtest,annual_forecast,solve_lots,greedy_lots

def run(data_dir,output,mode='private_local'):
    data_dir=Path(data_dir).resolve();output=Path(output).resolve()
    repo=Path(__file__).resolve().parents[1]
    if mode!='independent_synthetic' and (output==repo or repo in output.parents):
        raise ValueError('Private results must be written outside the public repository')
    if mode=='independent_synthetic':
        manifest=json.loads((data_dir/'manifest.json').read_text(encoding='utf-8'))
        if manifest['mode']!=mode or manifest['private_inputs_read'] is not False: raise ValueError('Not a synthetic manifest')
        for name,expected in manifest['sha256'].items():
            if sha256(data_dir/name)!=expected: raise ValueError('Demo data hash mismatch')
    output.mkdir(parents=True,exist_ok=True)
    panel=load_daily(data_dir/'daily.csv')
    products=pd.read_csv(data_dir/'products.csv')
    annual,panel_annual=load_annual(data_dir/'annual.csv')
    selected,selection,predictions,forecast_summary,cutoff=evaluate(panel)
    selection.to_csv(output/'model_selection.csv',index=False,lineterminator='\n')
    predictions.to_csv(output/'forecast_predictions.csv',index=False,lineterminator='\n')
    forecast_summary.to_csv(output/'forecast_summary.csv',index=False,lineterminator='\n')
    classes,inventory_detail,trace=simulate(panel,products,selected,cutoff)
    classes.to_csv(output/'abc_xyz.csv',index=False,lineterminator='\n')
    inventory_detail.to_csv(output/'inventory_by_sku.csv',index=False,lineterminator='\n')
    trace.to_csv(output/'inventory_trace.csv',index=False,lineterminator='\n')
    inventory_summary=aggregate_results(inventory_detail)
    inventory_summary.to_csv(output/'inventory_summary.csv',index=False,lineterminator='\n')
    sensitivity=[]
    for factor in [0.7,1.0,1.3]:
        detail=inventory_detail if factor==1 else simulate(panel,products,selected,cutoff,factor,False)[1]
        for multiplier in [2.,5.,10.]: sensitivity.append(aggregate_results(detail,multiplier))
    pd.concat(sensitivity,ignore_index=True).to_csv(output/'inventory_sensitivity.csv',index=False,lineterminator='\n')
    annual_detail,annual_summary=annual_backtest(panel_annual)
    annual_detail.to_csv(output/'annual_print_backtest.csv',index=False,lineterminator='\n')
    annual_summary.to_csv(output/'annual_print_summary.csv',index=False,lineterminator='\n')
    targets=np.array([annual_forecast(panel_annual[sku].values) for sku in panel_annual])
    # Priority comes exclusively from history; constraints/costs are authored assumptions.
    rank=pd.Series(panel_annual.sum().rank(pct=True).values)
    penalties=np.where(rank>=0.8,9.,np.where(rank>=0.4,5.,3.))
    full_capacity=max(100,int(np.ceil(targets/50).sum()*50))
    production_rows=[];production_summary=[]
    for factor in [0.5,0.75,1.0]:
        capacity=int(full_capacity*factor)//50*50
        optimal,solver=solve_lots(targets,capacity,shortage_cost=penalties)
        greedy=greedy_lots(targets,capacity,penalties)
        for policy,quantities in [('milp',optimal),('priority_greedy',greedy)]:
            under=np.maximum(targets-quantities,0);over=np.maximum(quantities-targets,0)
            objective=float(under@penalties+over.sum()+30*(quantities>0).sum())
            production_summary.append({'capacity_factor':factor,'policy':policy,'capacity':capacity,
                'planned_units':int(quantities.sum()),'underage':float(under.sum()),'overage':float(over.sum()),
                'objective':objective,'solver_status':solver['status'] if policy=='milp' else None,
                'mip_gap':solver['mip_gap'] if policy=='milp' else None,
                'dual_bound':solver['dual_bound'] if policy=='milp' else None})
            production_rows.extend({'capacity_factor':factor,'policy':policy,'sku':sku,'forecast_target':float(target),
                'scenario_usable_stock':0,'print_qty':int(q),'batch_size':50,'minimum_batches':2,
                'underage':float(u),'overage':float(o),'scenario_shortage_cost':float(cost)}
                for sku,target,q,u,o,cost in zip(panel_annual.columns,targets,quantities,under,over,penalties))
    production_summary=pd.DataFrame(production_summary)
    production_summary.to_csv(output/'production_summary.csv',index=False,lineterminator='\n')
    pd.DataFrame(production_rows).to_csv(output/'production_plan.csv',index=False,lineterminator='\n')
    summary={'data_mode':mode,'daily':{'skus':len(panel.columns),'days':len(panel),
        'start':str(panel.index.min().date()),'end':str(panel.index.max().date()),
        'selection_end':str(panel.index[cutoff-1].date()),'holdout_days':len(panel)-cutoff,
        'horizon_days':7,'validation_days':42,'test_origins':(len(panel)-cutoff)//7},
        'annual':{'cohorts':len(panel_annual.columns),'years':[int(v) for v in panel_annual.index],
            'test_years':[int(v) for v in panel_annual.index[3:]]},
        'forecast':forecast_summary.astype(object).where(pd.notna(forecast_summary),None).to_dict('records'),
        'inventory':inventory_summary.to_dict('records'),'production':production_summary.astype(object).where(pd.notna(production_summary),None).to_dict('records'),
        'data_sha256':{name:sha256(data_dir/name) for name in ['daily.csv','products.csv','annual.csv']},
        'assumptions':{'inventory':'lost sales; hypothetical initial stock, lead times, batches, costs; no actual supplier history',
            'production':'single-period total unit capacity; zero compatible usable stock; no machine sequencing',
            'interpretation':'retrospective experiments and scenario simulation; no deployed business impact claimed'}}
    write_json(output/'summary.json',summary)
    write_report(output,summary,annual_summary)
    figures(output,forecast_summary,inventory_summary,production_summary)
    return summary

def write_report(output,summary,annual_summary):
    forecast=summary['forecast'];selected=next(r for r in forecast if r['model']=='selected')
    baseline=next(r for r in forecast if r['model']=='seasonal_naive')
    change=(baseline['wape']-selected['wape'])/baseline['wape'] if baseline['wape'] else None
    change_label=f'{change:+.2%}' if change is not None else 'undefined (zero denominator)'
    lines=['# Reproducible experiment results','',f"Data mode: **{summary['data_mode']}**. All costs are scenario cost units.",'',
        f"Daily panel: {summary['daily']['skus']} SKUs × {summary['daily']['days']} days. "
        f"Final {summary['daily']['holdout_days']} days, eight nonoverlapping 7-day origins; 42-day pretest validation.",'',
        '## 1. Demand forecast','',
        '| Model | WAPE ↓ | Bias | MAE ↓ | MASE ↓ |','|---|---:|---:|---:|---:|']
    for r in forecast:
        mase='undefined' if r['mase'] is None else f"{r['mase']:.3f}"
        wape='undefined' if r['wape'] is None else f"{r['wape']:.2%}"
        bias='undefined' if r['bias'] is None else f"{r['bias']:.2%}"
        lines.append(f"| {r['model']} | {wape} | {bias} | {r['mae']:.3f} | {mase} |")
    lines+=['',f"Selected-model WAPE relative change vs seasonal naive: **{change_label}** (positive means lower error). "
        'This is a descriptive comparison on one panel; no statistical significance or business savings claim.',
        '', '![Forecast error by method](forecast_error.png)','',
        '## 2. Inventory policy simulation','','| Policy | Unit fill rate ↑ | Service cost ↓ | Lost units | End stock | End pipeline |',
        '|---|---:|---:|---:|---:|---:|']
    for r in summary['inventory']:
        fill='undefined' if r['fill_rate'] is None else f"{r['fill_rate']:.2%}"
        lines.append(f"| {r['policy']} | {fill} | {r['service_cost']:,.1f} | {r['lost_units']:,.0f} | {r['ending_stock']:,.0f} | {r['ending_pipeline']:,.0f} |")
    lines+=['','Costs = end-of-day holding + fixed order costs + lost-sales penalty; purchases and terminal stock value excluded. ',
        'Nominal cycle-service parameters are policy inputs, not observed fill-rate guarantees. ',
        'See `inventory_sensitivity.csv` for 27 policy/lead-time/shortage-cost scenarios. ',
        '![Inventory service and cost](inventory_tradeoff.png)','',
        '## 3. Return-aware print planning and capacity allocation','',
        f"Annual cohort panel: {summary['annual']['cohorts']} cohorts; evaluated years {summary['annual']['test_years']}. "
        'Very short annual histories limit generalization. Overage is a proxy for return/inventory exposure; it is not measured returns.',
        '','| Policy | Critical fractile | Scenario loss | Overage | Underage |','|---|---:|---:|---:|---:|']
    for r in annual_summary.to_dict('records'):
        lines.append(f"| {r['policy']} | {r['critical_fractile']:.0%} | {r['scenario_loss']:,.0f} | {r['overage']:,.0f} | {r['underage']:,.0f} |")
    lines+=['','The independent capacity experiment plans against forecasts, not future realized demand. ',
        'MILP and the feasible greedy comparator share the objective, capacity, lot size and minimum-lot constraints.',
        '','| Capacity factor | Policy | Planned units | Objective ↓ | MILP gap |','|---|---|---:|---:|---:|']
    for r in summary['production']:
        gap='—' if r['mip_gap'] is None else f"{r['mip_gap']:.3g}"
        lines.append(f"| {r['capacity_factor']:.0%} | {r['policy']} | {r['planned_units']:,} | {r['objective']:,.1f} | {gap} |")
    lines+=['','![Capacity planning objectives](capacity_objective.png)','',
        '## Interpretation limits','',
        ('- This public report uses independently authored synthetic data; no original records or local-only results are included.'
         if summary['data_mode']=='independent_synthetic' else
         '- This private report uses normalized local shipment and planning aggregates. Keep this report outside the public repository.'),
        '- Observed shipments can be constrained by historical availability; unconstrained demand is not identifiable without stockout logs.',
        '- Dense zero-sales dates require ingestion completeness; absent global source dates must be investigated before filling.',
        '- Costs, lead times, opening inventories, capacity and batch constraints are scenario assumptions.',
        '- Forecast selection uses pretest data only; coefficients update from past observations at each test origin.',
        '- Annual cohort mapping may include selection and version-change bias; five annual observations do not support an elaborate forecast.',
        '- These three experiments share schemas but do not form a coupled, deployed ERP or finite-machine scheduling system.','']
    (output/'RESULTS.md').write_text('\n'.join(line.rstrip() for line in lines),encoding='utf-8',newline='\n')

def figures(output,forecast,inventory,production):
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'axes.spines.top':False,
        'axes.spines.right':False,'axes.labelcolor':'#253247','text.color':'#253247','figure.facecolor':'white'})
    blue='#3566a5';gold='#c18c26';grey='#65748b'
    f=forecast[forecast.wape.notna()].sort_values('wape',ascending=True)
    fig,ax=plt.subplots(figsize=(10,4.6));colors=[gold if m=='selected' else blue for m in f.model]
    if len(f):
        ax.barh(f.model,f.wape*100,color=colors)
        for i,v in enumerate(f.wape*100):ax.text(v+0.6,i,f'{v:.1f}%',va='center')
    else:ax.text(.5,.5,'WAPE undefined: no observed test demand',transform=ax.transAxes,ha='center')
    ax.invert_yaxis();ax.set(xlabel='WAPE (%) — lower is better',title='7-day rolling forecasts | 56-day final holdout',xlim=(0,max(1,float(f.wape.max()*100*1.2))) if len(f) else (0,1))
    ax.grid(axis='x',alpha=.15);ax.set_axisbelow(True);fig.tight_layout();fig.savefig(output/'forecast_error.png',dpi=160);plt.close(fig)
    fig,ax=plt.subplots(figsize=(10,4.6))
    for r,color,marker in zip(inventory.to_dict('records'),[blue,gold,grey],['o','s','^']):
        if r['fill_rate'] is not None:
            ax.scatter(r['fill_rate']*100,r['service_cost'],color=color,marker=marker,s=90,label=r['policy'])
    ax.set(xlabel='Unit fill rate (%) — higher is better',ylabel='Scenario service cost — lower is better',title='Policy trade-off | hypothetical inventory system')
    if ax.collections:ax.legend(loc='best',frameon=False)
    else:ax.text(.5,.5,'Fill rate undefined: no observed test demand',transform=ax.transAxes,ha='center')
    ax.grid(alpha=.15);ax.ticklabel_format(axis='y',style='plain');fig.tight_layout();fig.savefig(output/'inventory_tradeoff.png',dpi=160);plt.close(fig)
    fig,ax=plt.subplots(figsize=(10,4.6));x=np.arange(3)
    for offset,policy,color in [(-.18,'milp',blue),(.18,'priority_greedy',gold)]:
        g=production[production.policy==policy].sort_values('capacity_factor')
        ax.bar(x+offset,g.objective,width=.34,color=color,label=policy)
    ax.set_xticks(x,['50%','75%','100%']);ax.set(xlabel='Capacity as share of rounded forecast target',ylabel='Scenario objective — lower is better',title='Identical capacity and minimum-lot constraints')
    ax.legend(frameon=False);ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True);fig.tight_layout();fig.savefig(output/'capacity_objective.png',dpi=160);plt.close(fig)

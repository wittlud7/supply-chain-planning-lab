from itertools import product
import numpy as np
import pandas as pd
import pytest
from supplychain.data import generate_demo,load_daily,load_annual
from supplychain.forecast import MODELS,predict,select_models,evaluate
from supplychain.inventory import simulate
from supplychain.production import solve_lots,greedy_lots,annual_backtest
from supplychain.pipeline import run

def fixture_panel():
    dates=pd.date_range('2024-01-01',periods=168)
    return pd.DataFrame({'A':np.resize([10.,4.,12.,7.,8.,0.,0.],168),
        'B':np.resize([0.,0.,0.,20.,0.,0.,0.],168)},index=dates)

def test_synthetic_reproducible(tmp_path):
    generate_demo(tmp_path/'a',n_skus=4,n_days=168)
    generate_demo(tmp_path/'b',n_skus=4,n_days=168)
    for name in ['daily.csv','products.csv','annual.csv','manifest.json']:
        assert (tmp_path/'a'/name).read_bytes()==(tmp_path/'b'/name).read_bytes()
    assert load_daily(tmp_path/'a/daily.csv').shape==(168,4)

@pytest.mark.parametrize('model',MODELS)
def test_zero_demand_and_nonnegative_forecasts(model):
    assert np.array_equal(predict(np.zeros(80),10,model),np.zeros(10))
    result=predict(np.resize([0,5,0,0,2],80),15,model)
    assert len(result)==15 and np.isfinite(result).all() and (result>=0).all()

def test_selection_has_no_holdout_leakage():
    p=fixture_panel();cutoff=len(p)-56
    a=select_models(p,cutoff)
    p.iloc[cutoff:]=1e9
    b=select_models(p,cutoff)
    assert a[0]==b[0]
    pd.testing.assert_frame_equal(a[1],b[1])

def test_time_order_and_forecast_baseline():
    _,_,predictions,summary,_=evaluate(fixture_panel())
    assert (pd.to_datetime(predictions.train_end)<pd.to_datetime(predictions.origin)).all()
    assert (pd.to_datetime(predictions.origin)<=pd.to_datetime(predictions.date)).all()
    assert summary.set_index('model').loc['seasonal_naive','wape']==pytest.approx(0)
    selected=predictions[predictions.model=='selected']
    assert not selected.duplicated(['sku','date']).any()

def test_missing_dates_and_duplicates_rejected(tmp_path):
    p=tmp_path/'daily.csv'
    pd.DataFrame({'date':['2024-01-01','2024-01-03'],'sku':['A','A'],'demand':[1,2]}).to_csv(p,index=False)
    with pytest.raises(ValueError,match='Incomplete panel'):load_daily(p)
    pd.DataFrame({'date':['2024-01-01']*2,'sku':['A']*2,'demand':[1,2]}).to_csv(p,index=False)
    with pytest.raises(ValueError,match='Duplicate'):load_daily(p)

def test_inventory_flow_conservation_and_lead_times():
    panel=fixture_panel();cutoff=len(panel)-56
    products=pd.DataFrame({'sku':['A','B'],'lead_time_days':[3,5],'batch_size':[5,10],'unit_cost':[2.,1.]})
    selected=select_models(panel,cutoff)[0]
    _,detail,trace=simulate(panel,products,selected,cutoff)
    for (_,sku),g in trace.groupby(['policy','sku']):
        g=g.sort_values('date');stock=float(g.initial_on_hand.iloc[0]);arrivals={}
        for day,r in enumerate(g.itertuples()):
            assert r.received==pytest.approx(arrivals.get(day,0))
            assert stock+r.received-r.filled==pytest.approx(r.end_on_hand)
            assert r.filled+r.lost==pytest.approx(r.demand)
            assert r.end_on_hand>=0 and r.lost>=0
            batch=products.set_index('sku').loc[sku,'batch_size']
            assert r.ordered%batch==0
            arrivals[day+r.lead_time_days]=arrivals.get(day+r.lead_time_days,0)+r.ordered
            stock=r.end_on_hand
    assert np.allclose(detail.initial_stock+detail.ordered_units-detail.filled,detail.ending_stock+detail.ending_pipeline)

def test_milp_matches_exhaustive_small_problem():
    target=np.array([130.,80.,170.]);penalty=np.array([9.,3.,5.]);capacity=250
    q,info=solve_lots(target,capacity,shortage_cost=penalty)
    def objective(plan):
        plan=np.array(plan);return np.maximum(target-plan,0)@penalty+np.maximum(plan-target,0).sum()+30*(plan>0).sum()
    feasible=[v for v in product([0,100,150,200,250],repeat=3) if sum(v)<=capacity]
    assert info['objective']==pytest.approx(min(objective(v) for v in feasible))
    assert info['mip_gap']<=1e-8
    greedy=greedy_lots(target,capacity,penalty)
    assert info['objective']<=objective(greedy)+1e-7
    assert q.sum()<=capacity

def test_zero_capacity_means_all_shortage():
    q,info=solve_lots([100.,50.],0)
    assert np.array_equal(q,[0,0])
    assert info['objective']==pytest.approx(750.)

def test_annual_calibration_has_no_future_leakage():
    panel=pd.DataFrame({'A':[100.,110.,120.,130.,140.],'B':[90.,80.,70.,60.,50.]},index=range(2020,2025))
    a=annual_backtest(panel)[0];panel.iloc[-1]=1e8;b=annual_backtest(panel)[0]
    pd.testing.assert_frame_equal(a[a.year==2023].reset_index(drop=True),b[b.year==2023].reset_index(drop=True))
    assert (a.calibration_latest_year<a.year).all()

def test_private_results_cannot_be_written_in_repository(tmp_path):
    from supplychain import pipeline
    with pytest.raises(ValueError,match='outside the public repository'):
        run(tmp_path, __import__('pathlib').Path(pipeline.__file__).parents[1]/'reports/leak')

def test_zero_demand_pipeline_reports_undefined_rates(tmp_path):
    import json
    data=tmp_path/'inputs';generate_demo(data,n_skus=2,n_days=168)
    daily=pd.read_csv(data/'daily.csv');daily['demand']=0;daily.to_csv(data/'daily.csv',index=False)
    result=run(data,tmp_path/'results')
    assert all(row['wape'] is None and row['mase'] is None for row in result['forecast'])
    assert all(row['fill_rate'] is None for row in result['inventory'])
    saved=json.loads((tmp_path/'results/summary.json').read_text(encoding='utf-8'))
    assert saved['forecast'][0]['wape'] is None

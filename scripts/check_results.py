"""Reconcile shipped result tables independently of report prose."""
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]/'reports/demo'

def main():
    predictions=pd.read_csv(ROOT/'forecast_predictions.csv')
    summary=pd.read_csv(ROOT/'forecast_summary.csv').set_index('model')
    assert np.allclose(predictions.absolute_error,np.abs(predictions.actual-predictions.forecast))
    assert (pd.to_datetime(predictions.train_end)<pd.to_datetime(predictions.origin)).all()
    for method,g in predictions.groupby('model'):
        assert not g.duplicated(['sku','date']).any()
        assert np.isclose(summary.loc[method,'wape'],g.absolute_error.sum()/g.actual.sum())
    inventory=pd.read_csv(ROOT/'inventory_by_sku.csv')
    assert np.allclose(inventory.initial_stock+inventory.ordered_units-inventory.filled,inventory.ending_stock+inventory.ending_pipeline)
    assert np.allclose(inventory.demand,inventory.filled+inventory.lost)
    trace=pd.read_csv(ROOT/'inventory_trace.csv')
    for _,g in trace.groupby(['policy','sku']):
        previous=np.r_[g.initial_on_hand.iloc[0],g.end_on_hand.values[:-1]]
        assert np.allclose(previous+g.received-g.filled,g.end_on_hand)
    plans=pd.read_csv(ROOT/'production_plan.csv')
    production=pd.read_csv(ROOT/'production_summary.csv')
    for factor,g in production.groupby('capacity_factor'):
        scores=g.set_index('policy')
        assert scores.loc['milp','objective']<=scores.loc['priority_greedy','objective']+1e-5
        for method,rows in plans[plans.capacity_factor==factor].groupby('policy'):
            assert rows.print_qty.sum()<=scores.loc[method,'capacity']
            assert (rows.print_qty%rows.batch_size==0).all()
            assert ((rows.print_qty==0)|(rows.print_qty>=rows.minimum_batches*rows.batch_size)).all()
    print('PASS: forecast metrics, chronological boundaries, inventory flow and production constraints reconciled.')

if __name__=='__main__':main()

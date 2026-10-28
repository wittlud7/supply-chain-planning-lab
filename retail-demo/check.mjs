import assert from 'node:assert/strict';
import {writeFileSync} from 'node:fs';
import {generate,forecast,choose,evaluate,simulate,compare,nextPlan,METHODS} from './engine.mjs';
const data=generate();
assert.deepEqual(generate(),data);
assert.equal(data.series.length,72);
assert.equal(data.series.reduce((s,x)=>s+x.rows.length,0),15120);
const first=data.series[0];
const original=forecast(first,182,7,'promo');
const changed=structuredClone(first);
changed.rows.slice(182).forEach(r=>{r.sales=99999;r.demand=99999;r.censored=true;});
assert.deepEqual(forecast(changed,182,7,'promo'),original);
assert.equal(choose(changed),choose(first));
const hidden=structuredClone(first);hidden.rows.forEach(r=>r.demand=123456);
for(const m of Object.keys(METHODS))assert.deepEqual(forecast(hidden,182,7,m),forecast(first,182,7,m));
assert.equal(choose(hidden),choose(first));
for(const item of data.series)for(const lead of [1,2,3,7])for(const policy of ['cover','balanced','cautious']) {
  const r=simulate(item,choose(item),{lead,policy});
  assert.equal(r.initial+r.received,r.sold+r.waste+r.ending);
  assert.equal(r.ordered,r.received+r.transit);
  for(const d of r.daily){assert.equal(d.order%item.pack,0);assert(d.position+d.order<=item.capacity);assert(d.end>=0);assert(d.sold+d.lost===d.demand);}
}
const all=evaluate(data),byStore=Array.from({length:6},(_,s)=>evaluate(data,{store:`门店${s+1}`}));
assert.equal(all.details.length,2016);
assert.equal(byStore.reduce((s,x)=>s+x.details.length,0),all.details.length);
for(const item of all.items){const p=nextPlan(item,all.selected[item.id]);assert.equal(p.order%item.pack,0);assert(p.onhand+p.intransit+p.order<=item.capacity);}
const empty=evaluate(data,{store:'missing'});assert.equal(empty.metrics.selected.wape,null);
const policies=compare(all);
const report={seed:data.seed,stores:6,skus:12,series:72,days:210,rows:15120,validation:'2026-06-04—2026-07-01',test:'2026-07-02—2026-07-29',metrics:all.metrics,policies:policies.map(({runs,...r})=>r),checks:['deterministic generation','future-data isolation','hidden-demand isolation','validation-only model selection','864 inventory paths with conservation and capacity checks','pack multiples','filter partition','next-plan constraints','empty-scope handling']};
if(process.argv.includes('--write'))writeFileSync(new URL('./results.json',import.meta.url),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report,null,2));

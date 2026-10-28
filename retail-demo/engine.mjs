// Independent synthetic retail experiment. No company data or external services.
export const SEED = 20261028;
export const METHODS = {mean28:'28日均值', weekday:'同星期均值', promo:'星期与已知促销'};
export const POLICIES = {cover:'固定4天覆盖', balanced:'预测与安全缓冲', cautious:'预测与较高缓冲'};
const mean = a => a.length ? a.reduce((s,x)=>s+x,0)/a.length : 0;
const sd = a => Math.sqrt(mean(a.map(x=>(x-mean(a))**2)));
const date = t => new Date(Date.UTC(2026,0,1+t)).toISOString().slice(0,10);
export const weekday = t => new Date(Date.UTC(2026,0,1+t)).getUTCDay();
export function promoAt(t,k) {return (t+k*3)%35>=28 ? 1.35 : 1;}
export function generate(seed=SEED) {
  let state=seed>>>0;
  const random=()=>{state=(1664525*state+1013904223)>>>0;return state/4294967296;};
  const specs=[['鲜奶','短保',5,6,80,18],['原味酸奶','短保',7,6,72,12],['全麦面包','短保',3,4,48,12],['鲜豆腐','短保',3,4,48,10],['冷冻水饺','冷冻',90,6,72,8],['冷冻玉米','冷冻',90,6,60,7],['冷冻馄饨','冷冻',90,6,72,9],['冰淇淋','冷冻',60,6,60,7],['纸巾','标品',180,6,90,10],['饮用水','标品',180,12,144,24],['洗衣液','标品',180,4,48,5],['挂面','标品',180,6,72,9]];
  const series=[];
  for(let s=0;s<6;s++) for(let k=0;k<specs.length;k++) {
    const [name,category,life,pack,capacity,base]=specs[k];
    const rows=[];
    for(let t=0;t<210;t++) {
      const weekend=[0,6].includes(weekday(t))?1.22:1;
      const trend=1+t/210*0.12;
      const demand=Math.max(0,Math.round(base*(0.75+s*0.1)*weekend*trend*promoAt(t,k)*(0.6+random()*0.8)));
      // Exogenous synthetic supply incident; true demand is evaluation-only.
      const censored=random()<0.10;
      const sales=censored?Math.floor(demand*(0.35+random()*0.35)):demand;
      rows.push({t,date:date(t),sales,censored,demand});
    }
    series.push({id:`S${s+1}-P${String(k+1).padStart(2,'0')}`,store:`门店${s+1}`,sku:k,name,category,life,pack,capacity,base,rows});
  }
  return {seed,days:210,trainEnd:154,validationEnd:182,testEnd:210,series};
}
export function forecast(item,origin,horizon,method='promo',adjust=true) {
  if(!(method in METHODS)||origin<28||origin>item.rows.length||horizon<1) throw Error('Invalid forecast request');
  // ONLY rows before origin are accessed; stockout days are excluded, not divided by guessed availability.
  const history=item.rows.slice(Math.max(0,origin-28),origin);
  let clean=adjust?history.filter(r=>!r.censored):history;
  if(!clean.length) clean=history;
  const fallback=mean(clean.map(r=>r.sales));
  return Array.from({length:horizon},(_,h)=>{
    const t=origin+h;
    if(method==='mean28')return fallback;
    const same=clean.filter(r=>weekday(r.t)===weekday(t));
    const pool=same.length?same:clean;
    if(method==='weekday')return mean(pool.map(r=>r.sales));
    return mean(pool.map(r=>r.sales/promoAt(r.t,item.sku)))*promoAt(t,item.sku);
  });
}
export function score(pairs) {
  const actual=pairs.reduce((s,[a])=>s+a,0), abs=pairs.reduce((s,[a,p])=>s+Math.abs(p-a),0);
  return {wape:actual?abs/actual:null,bias:actual?pairs.reduce((s,[a,p])=>s+p-a,0)/actual:null,mae:pairs.length?abs/pairs.length:null,n:pairs.length};
}
export function choose(item,adjust=true) {
  let best='mean28',error=Infinity;
  for(const method of Object.keys(METHODS)) {
    const pairs=[];
    for(let o=154;o<182;o+=7) {
      const pred=forecast(item,o,7,method,adjust);
      for(let h=0;h<7;h++) {
        const r=item.rows[o+h];
        // Model selection cannot inspect hidden demand. Use only uncensored sales.
        if(!r.censored)pairs.push([r.sales,pred[h]]);
      }
    }
    const err=score(pairs).mae ?? Infinity;
    if(err<error){error=err;best=method;}
  }
  return best;
}
export function evaluate(data,{store='all',category='all',adjust=true}={}) {
  const items=data.series.filter(x=>(store==='all'||x.store===store)&&(category==='all'||x.category===category));
  const pairs=Object.fromEntries([...Object.keys(METHODS),'selected'].map(k=>[k,[]]));
  const selected={},details=[];
  for(const item of items) {
    const method=choose(item,adjust);selected[item.id]=method;
    for(let o=182;o<210;o+=7) {
      for(const key of Object.keys(pairs)) {
        const p=forecast(item,o,7,key==='selected'?method:key,adjust);
        for(let h=0;h<7;h++)pairs[key].push([item.rows[o+h].demand,p[h]]);
        if(key==='selected')for(let h=0;h<7;h++)details.push({id:item.id,t:o+h,actual:item.rows[o+h].demand,sales:item.rows[o+h].sales,pred:p[h]});
      }
    }
  }
  return {items,selected,details,metrics:Object.fromEntries(Object.entries(pairs).map(([k,v])=>[k,score(v)]))};
}
export function simulate(item,method,{lead=2,policy='balanced',adjust=true}={}) {
  if(!Number.isInteger(lead)||lead<1||lead>7||!(policy in POLICIES))throw Error('Invalid simulation settings');
  const history=item.rows.slice(154,182).filter(r=>!adjust||!r.censored).map(r=>r.sales);
  const initial=Math.min(item.capacity,Math.round(mean(history)*2));
  let lots=[{qty:initial,expiry:182+item.life-1}],pipeline=[],sold=0,lost=0,waste=0,ordered=0,received=0,holding=0;
  const daily=[];
  for(let t=182;t<210;t++) {
    for(const order of pipeline.filter(o=>o.arrival===t)) {lots.push({qty:order.qty,expiry:t+item.life-1});received+=order.qty;}
    pipeline=pipeline.filter(o=>o.arrival>t);
    const onhand=lots.reduce((s,l)=>s+l.qty,0),intransit=pipeline.reduce((s,o)=>s+o.qty,0),position=onhand+intransit;
    const p=forecast(item,t,lead+1,method,adjust);
    const target=policy==='cover'?mean(history)*4:p.reduce((s,x)=>s+x,0)+(policy==='cautious'?1.8:0.9)*sd(history)*Math.sqrt(lead+1);
    const raw=Math.max(0,target-position);
    // Conservative total-position capacity bound. Pack rounding never violates it.
    const capacityLimit=Math.floor(Math.max(0,item.capacity-position)/item.pack)*item.pack;
    const q=Math.min(Math.ceil(raw/item.pack)*item.pack,capacityLimit);
    if(q>0){pipeline.push({qty:q,arrival:t+lead});ordered+=q;}
    const demand=item.rows[t].demand;let remaining=demand,fulfilled=0;
    lots.sort((a,b)=>a.expiry-b.expiry);
    for(const lot of lots){const take=Math.min(lot.qty,remaining);lot.qty-=take;remaining-=take;fulfilled+=take;}
    const expired=lots.filter(l=>l.expiry<=t).reduce((s,l)=>s+l.qty,0);
    lots=lots.filter(l=>l.expiry>t&&l.qty>0);
    const end=lots.reduce((s,l)=>s+l.qty,0);
    sold+=fulfilled;lost+=remaining;waste+=expired;holding+=end;
    daily.push({t,date:date(t),demand,sold:fulfilled,lost:remaining,waste:expired,order:q,received:received-(daily.at(-1)?.receivedTotal||0),receivedTotal:received,end,intransit:pipeline.reduce((s,o)=>s+o.qty,0),target,raw,position,capacityLimit});
  }
  const ending=lots.reduce((s,l)=>s+l.qty,0),transit=pipeline.reduce((s,o)=>s+o.qty,0);
  if(initial+received!==sold+waste+ending||ordered!==received+transit)throw Error('Inventory conservation failed');
  return {initial,received,ordered,sold,lost,waste,ending,transit,avgInventory:holding/28,fill:sold/(sold+lost||1),wasteRate:waste/(initial+received||1),daily};
}
export function compare(evaluation,opts={}) {
  return Object.keys(POLICIES).map(policy=>{
    const runs=evaluation.items.map(x=>({item:x,...simulate(x,evaluation.selected[x.id],{...opts,policy})}));
    const sum=k=>runs.reduce((s,r)=>s+r[k],0);
    return {policy,runs,sold:sum('sold'),lost:sum('lost'),waste:sum('waste'),fill:sum('sold')/(sum('sold')+sum('lost')||1),wasteRate:sum('waste')/(sum('initial')+sum('received')||1),avgInventory:sum('avgInventory'),ending:sum('ending'),transit:sum('transit'),ordered:sum('ordered')};
  });
}
export function nextPlan(item,method,opts={}) {
  const {lead=2,policy='balanced',adjust=true}=opts;
  const run=simulate(item,method,opts),last=run.daily.at(-1),p=forecast(item,210,lead+1,method,adjust);
  const h=item.rows.slice(182,210).filter(r=>!adjust||!r.censored).map(r=>r.sales);
  const target=policy==='cover'?mean(h)*4:p.reduce((s,x)=>s+x,0)+(policy==='cautious'?1.8:0.9)*sd(h)*Math.sqrt(lead+1);
  const position=last.end+last.intransit,raw=Math.max(0,target-position);
  const q=Math.min(Math.ceil(raw/item.pack)*item.pack,Math.floor(Math.max(0,item.capacity-position)/item.pack)*item.pack);
  const risk=last.end<p[0]?'断货风险':item.life<=7&&last.end>mean(p)*item.life?'效期复核':q===0?'暂不补货':'常规补货';
  return {id:item.id,store:item.store,name:item.name,category:item.category,method,life:item.life,pack:item.pack,capacity:item.capacity,onhand:last.end,intransit:last.intransit,forecast:p.reduce((s,x)=>s+x,0),target,raw,order:q,risk};
}

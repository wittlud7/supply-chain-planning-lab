import {generate,evaluate,compare,nextPlan,score,METHODS,POLICIES} from './engine.mjs';
const data=generate(),$=id=>document.getElementById(id);
const pct=(x,d=1)=>x==null?'—':`${(x*100).toFixed(d)}%`,num=(x,d=0)=>Number(x).toLocaleString('zh-CN',{maximumFractionDigits:d});
let evaluation,comparisons,plans,settings,tab='forecast';
function chart(target,rows) {
  if(!rows.length){target.textContent='当前范围没有数据';return;}
  const days=[...new Set(rows.map(r=>r.t))],values=days.map(t=>{const a=rows.filter(r=>r.t===t);return {t,actual:a.reduce((s,r)=>s+r.actual,0),pred:a.reduce((s,r)=>s+r.pred,0)};});
  const w=720,h=220,p={l:45,r:12,t:20,b:32},max=Math.max(1,...values.flatMap(x=>[x.actual,x.pred]))*1.12;
  const x=i=>p.l+i/Math.max(1,values.length-1)*(w-p.l-p.r),y=v=>h-p.b-v/max*(h-p.t-p.b);
  const line=k=>values.map((v,i)=>`${x(i).toFixed(1)},${y(v[k]).toFixed(1)}`).join(' ');
  let grid='';for(let n=0;n<4;n++){const v=max*n/3;grid+=`<line x1="${p.l}" x2="${w-p.r}" y1="${y(v)}" y2="${y(v)}" stroke="#e4e8e0"/><text x="${p.l-10}" y="${y(v)+4}" text-anchor="end" fill="#89928b" font-size="10">${num(v)}</text>`;}
  const labels=[0,Math.floor((values.length-1)/2),values.length-1].map(i=>`<text x="${x(i)}" y="${h-7}" text-anchor="middle" fill="#89928b" font-size="10">${data.series[0].rows[values[i].t].date.slice(5)}</text>`).join('');
  target.innerHTML=`<svg viewBox="0 0 ${w} ${h}" aria-hidden="true">${grid}<polyline points="${line('actual')}" fill="none" stroke="#246b51" stroke-width="2.5"/><polyline points="${line('pred')}" fill="none" stroke="#b79363" stroke-width="2" stroke-dasharray="5 4"/>${labels}</svg>`;
  target.setAttribute('aria-label',`每日需求与预测，${values.length}天；模拟需求共${num(values.reduce((s,r)=>s+r.actual,0))}件，预测共${num(values.reduce((s,r)=>s+r.pred,0))}件。`);
}
const kpi=(label,value,note)=>`<div class="kpi"><label>${label}</label><strong>${value}</strong><small>${note}</small></div>`;
function render() {
  settings={lead:Number($('lead').value),policy:$('policy').value,adjust:$('adjust').checked};
  evaluation=evaluate(data,{store:$('store').value,category:$('category').value,adjust:settings.adjust});
  comparisons=compare(evaluation,settings);
  plans=evaluation.items.map(x=>nextPlan(x,evaluation.selected[x.id],settings));
  const metrics=evaluation.metrics.selected,actual=evaluation.details.reduce((s,r)=>s+r.actual,0),pred=evaluation.details.reduce((s,r)=>s+r.pred,0);
  $('scope').textContent=`${evaluation.items.length} 个门店商品组合　·　测试期 2026-07-02—07-29　·　7 天滚动预测　·　缺货日${settings.adjust?'排除':'保留'}　·　所有数量单位：件`;
  $('forecast-kpis').innerHTML=kpi('验证选模 WAPE',pct(metrics.wape),'测试期误差，越低越好')+kpi('预测偏差 Bias',pct(metrics.bias),'正值高估，负值低估')+kpi('测试期模拟需求',num(actual),'仅用于评估的潜在需求')+kpi('测试期预测总量',num(pred),'每个起点仅使用过去观测');
  chart($('forecast-chart'),evaluation.details);
  const maxError=Math.max(...Object.values(evaluation.metrics).map(r=>r.wape||0));
  $('model-comparison').innerHTML=Object.entries(evaluation.metrics).map(([key,r])=>`<div class="model-row ${key==='selected'?'selected':''}"><div class="model-label"><span>${METHODS[key]||'验证选模'}</span><span>${pct(r.wape)}</span></div><div class="track"><div class="bar" style="width:${(r.wape||0)/(maxError||1)*100}%"></div></div></div>`).join('');
  $('series-count').textContent=`${evaluation.items.length} 个组合`;
  $('forecast-table').innerHTML=evaluation.items.map(item=>{const rows=evaluation.details.filter(x=>x.id===item.id),m=score(rows.map(r=>[r.actual,r.pred]));return `<tr><td>${item.name}<small>${item.store} · ${item.id}</small></td><td>${item.category}</td><td>${METHODS[evaluation.selected[item.id]]}</td><td>${num(rows.reduce((s,r)=>s+r.actual,0))}</td><td>${num(rows.reduce((s,r)=>s+r.pred,0))}</td><td>${pct(m.wape)}</td><td>${pct(m.bias)}</td><td><button data-detail="${item.id}" aria-label="查看${item.store}${item.name}">查看 ↗</button></td></tr>`;}).join('');
  const current=comparisons.find(x=>x.policy===settings.policy),baseline=comparisons[0];
  $('inventory-kpis').innerHTML=kpi('需求数量满足率',pct(current.fill),'实际满足数量 ÷ 模拟需求')+kpi('平均日末库存',num(current.avgInventory,1),'范围内商品日末库存合计均值')+kpi('测试期报损',num(current.waste),'到期未售出的商品数量')+kpi('期末在途',num(current.transit),'计入订单守恒，不算已到货');
  $('policy-table').innerHTML=comparisons.map(r=>`<tr${r.policy===settings.policy?' style="background:#e8f0e9"':''}><td>${POLICIES[r.policy]}${r.policy===settings.policy?' · 当前':''}</td><td>${pct(r.fill,2)}</td><td>${num(r.avgInventory,1)}</td><td>${num(r.waste)}</td><td>${pct(r.wasteRate,3)}</td><td>${num(r.transit)}</td></tr>`).join('');
  const delta=(current.fill-baseline.fill)*100,inv=current.avgInventory-baseline.avgInventory;
  $('tradeoff').textContent=`当前策略相对固定覆盖：满足率${delta>=0?'增加':'减少'} ${Math.abs(delta).toFixed(2)} 个百分点，平均日末库存${inv>=0?'增加':'减少'} ${num(Math.abs(inv),1)} 件。该比较不代表真实经营收益；短保报损低也可能来自容量上限、效期及需求假设。`;
  $('plan-table').innerHTML=plans.map(p=>`<tr><td>${p.name}<small>${p.store} · 效期 ${p.life} 天 · ${p.pack} 件/箱</small></td><td>${num(p.onhand)} / ${num(p.intransit)}</td><td>${num(p.forecast,1)}</td><td>${num(p.target,1)}</td><td>${num(p.raw,1)}</td><td><strong>${num(p.order)}</strong></td><td><span class="risk ${p.risk.includes('风险')||p.risk.includes('复核')?'warn':''}">${p.risk}</span></td><td><button data-detail="${p.id}" aria-label="查看${p.store}${p.name}补货记录">查看 ↗</button></td></tr>`).join('');
}
function openDetail(id){const item=evaluation.items.find(x=>x.id===id),r=comparisons.find(x=>x.policy===settings.policy).runs.find(x=>x.item.id===id);$('detail-title').textContent=`${item.store} · ${item.name}`;$('detail-meta').textContent=`${METHODS[evaluation.selected[id]]}　/　${POLICIES[settings.policy]}　/　交期 ${settings.lead} 天　/　效期 ${item.life} 天　/　${item.pack} 件每箱`;
chart($('detail-chart'),evaluation.details.filter(x=>x.id===id));$('detail-table').innerHTML=r.daily.map(d=>`<tr><td>${d.date}</td><td>${d.demand}</td><td>${d.sold}</td><td>${d.lost}</td><td>${d.received}</td><td>${d.order}</td><td>${d.waste}</td><td>${d.end}</td></tr>`).join('');$('detail').showModal();}
document.addEventListener('click',e=>{const b=e.target.closest('[data-detail]');if(b)openDetail(b.dataset.detail);});
document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>{tab=b.dataset.tab;document.querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('active',x===b));for(const id of ['forecast','inventory','method'])$(`${id}-view`).hidden=id!==tab;const titles={forecast:['销量预测','比较预测基线，检查门店商品需求的高估与低估。'],inventory:['补货与库存','结合交期、整箱和效期，检查补货建议与库存权衡。'],method:['方法与边界','查看数据来源、指标口径、决策规则和适用限制。']};$('page-title').textContent=titles[tab][0];$('breadcrumb').textContent=titles[tab][0];$('page-intro').textContent=titles[tab][1];}));
for(const id of ['store','category','lead','adjust','policy'])$(id).addEventListener('change',render);
$('reset').addEventListener('click',()=>{$('store').value='all';$('category').value='all';$('lead').value='2';$('adjust').checked=true;$('policy').value='balanced';render();});
$('close').addEventListener('click',()=>$('detail').close());
$('detail').addEventListener('click',e=>{if(e.target===$('detail')){const r=$('detail').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)$('detail').close();}});
$('export').addEventListener('click',()=>{const header=['门店','商品','分类','预测方法','模拟决策日期','交期天数','效期天数','箱规件数','可售库存','在途','保护期预测','目标库存','初步缺口','建议件数','风险','策略','数据来源'];const rows=plans.map(p=>[p.store,p.name,p.category,METHODS[p.method],'2026-07-30',settings.lead,p.life,p.pack,p.onhand,p.intransit,p.forecast.toFixed(2),p.target.toFixed(2),p.raw.toFixed(2),p.order,p.risk,POLICIES[settings.policy],'独立合成数据']);const csv='\uFEFF'+[header,...rows].map(row=>row.map(v=>'"'+String(v).replaceAll('"','""')+'"').join(',')).join('\r\n');const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='模拟补货建议_20260730.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
render();

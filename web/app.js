"use strict";
const $ = id => document.getElementById(id);
const page = location.pathname.startsWith('/panels/f1') ? 'f1PanelPage' : location.pathname.startsWith('/panels/r1') ? 'r1PanelPage' : location.pathname.startsWith('/engineering') ? 'engineeringPage' : 'feederPage';
$(page).classList.add('active');
for (const link of document.querySelectorAll('nav a')) if (link.pathname === location.pathname || (page === 'feederPage' && link.pathname === '/feeder' && location.pathname === '/')) link.classList.add('active');
let snapshot = null, lastSeen = 0, historyBusy = false, historyTimer = null;
const pending = new Map();
const completed = new Map();
const colors = ['#51ddb5','#80b8f8','#f4c66c','#bca7ff','#e68072'];
const busNames = ['GRID_110KV','BUS_MV_SOURCE','BUS_R1_REMOTE','BUS_SS1_MV','BUS_SS1_LV'];
const b = (s,name) => s?.telemetry.buses.find(x => x.name === name);
const l = (s,name,end='from') => s?.telemetry.lines.find(x => x.name === name && x.end === end);
const t = (s,name) => s?.telemetry.transformers.find(x => x.name === name);
const br = (s,name) => s?.breakers.find(x => x.breaker === name);
const finite = v => typeof v === 'number' && Number.isFinite(v);
function fmt(v,dec=2,unit=''){return finite(v) ? `${v.toFixed(dec)}${unit}` : '—';}
function put(id,text,cls){const el=$(id);if(!el)return;el.textContent=text;el.classList.remove('good','off','warn');if(cls)el.classList.add(cls);}
function quality(o,stale){return stale?'UNKNOWN':o?.quality || 'UNKNOWN';}
function energization(o,stale){const q=quality(o,stale);return q==='GOOD'?'good':q==='NOT_ENERGIZED'?'off':'unknown';}
function position(status,stale){return stale?'UNKNOWN':status?.state || 'UNKNOWN';}
function displayVoltage(bus,stale,scale=1,unit='kV',compact=false){return stale?'UNKNOWN':quality(bus,false)==='GOOD'?fmt(bus.vm_kv*scale,scale===1000?0:2,` ${unit}`):quality(bus,false)==='NOT_ENERGIZED'?(compact?'OFF':'NOT ENERGIZED'):'UNKNOWN';}
function displayCurrent(line,stale,compact=false){return stale?'UNKNOWN':quality(line,false)==='GOOD'?fmt(line.i_ka,3,' kA'):quality(line,false)==='NOT_ENERGIZED'?(compact?'NO DATA':'UNAVAILABLE'):'UNKNOWN';}
function putDiagram(id,value,asset,stale){put(id,value,quality(asset,stale)==='GOOD'?'good':quality(asset,stale)==='NOT_ENERGIZED'?'off':'unknown');$(id).setAttribute('aria-label',`${id}: ${quality(asset,stale)==='NOT_ENERGIZED'?'not energized; measurement unavailable':value}`);}
function setWire(id,state){const el=$(id);el.classList.remove('good','off','unknown');el.classList.add(state);}
function setLamp(id,mode){const el=$(id);el.classList.remove('good','off','warn');if(mode)el.classList.add(mode);}
function setConnection(good){const el=$('connection');el.className='live-indicator '+(good?'good':'bad');el.lastElementChild.textContent=good?'Live':'Unknown';}

function render(s,stale=false){
  if(!s)return;
  $('staleAlert').hidden=!stale;
  setConnection(!stale);
  put('scanTime',stale?'UNKNOWN':s.ts.replace('T',' ').replace('Z',' UTC'));
  const f=br(s,'BRK_F1'),r=br(s,'BRK_R1'),grid=b(s,'GRID_110KV'),source=b(s,'BUS_MV_SOURCE'),remote=b(s,'BUS_R1_REMOTE'),mv=b(s,'BUS_SS1_MV'),lv=b(s,'BUS_SS1_LV'),l1=l(s,'L1_FEEDER_HEAD'),l2=l(s,'L2_FEEDER_TAIL'),t1=t(s,'T1_PRIMARY'),t2=t(s,'T2_SS1');
  const fPos=position(f,stale),rPos=position(r,stale);
  putDiagram('gridValue',displayVoltage(grid,stale,1,'kV',true),grid,stale);putDiagram('sourceValue',displayVoltage(source,stale,1,'kV',true),source,stale);putDiagram('remoteValue',displayVoltage(remote,stale,1,'kV',true),remote,stale);putDiagram('ss1MvValue',displayVoltage(mv,stale,1,'kV',true),mv,stale);putDiagram('lvValue',displayVoltage(lv,stale,1000,'V',true),lv,stale);
  putDiagram('t1Value',stale?'UNKNOWN':quality(t1,false)==='GOOD'?fmt(t1.loading_percent,1,' % loading'):'UNKNOWN',t1,stale);
  putDiagram('t2Value',stale?'UNKNOWN':quality(t2,false)==='GOOD'?fmt(t2.loading_percent,1,' % loading'):quality(t2,false)==='NOT_ENERGIZED'?'OFF':'UNKNOWN',t2,stale);
  putDiagram('l1Value',displayCurrent(l1,stale,true),l1,stale);putDiagram('l2Value',displayCurrent(l2,stale,true),l2,stale);
  putDiagram('loadValue',stale?'UNKNOWN':quality(lv,false)==='GOOD'?fmt(-lv.p_mw,2,' MW'):'NO DATA',lv,stale);
  putDiagram('loadQValue',stale?'UNKNOWN':quality(lv,false)==='GOOD'?fmt(-lv.q_mvar,2,' MVAr'):'NO DATA',lv,stale);
  put('f1Value',fPos);put('r1Value',rPos);put('f1Latch',stale?'UNKNOWN':f.tripped?'TRIP LATCHED':'LATCH CLEAR');put('r1Latch',stale?'UNKNOWN':r.tripped?'TRIP LATCHED':'LATCH CLEAR');
  setWire('wireSource',energization(source,stale));setWire('wireL1',energization(l1,stale));setWire('wireL2',energization(l2,stale));setWire('wireLv',energization(lv,stale));
  document.querySelectorAll('svg g.station').forEach((el,i)=>{el.classList.remove('good','off','unknown');el.classList.add(energization([grid,source,remote,mv,lv][i],stale));});
  document.querySelectorAll('svg g.transformer').forEach((el,i)=>{el.classList.remove('good','off','unknown');el.classList.add(energization([t1,t2][i],stale));});
  const loadEl=document.querySelector('svg g.load');loadEl.classList.remove('good','off','unknown');loadEl.classList.add(energization(lv,stale));
  for(const [id,status,pos] of [['f1Symbol',f,fPos],['r1Symbol',r,rPos]]){const el=$(id);el.classList.remove('open','closed','unknown','trip');el.classList.add(pos==='CLOSED'?'closed':pos==='OPEN'?'open':'unknown');if(!stale&&status.tripped)el.classList.add('trip');}
  put('topologyCaption',stale||[grid,source,remote,mv,lv].some(asset=>quality(asset,false)==='UNKNOWN')?'Topology UNKNOWN — waiting for a valid scan':!remote.energized?'F1 isolation: remote point and SS1 de-energized':!mv.energized?'R1 isolation: remote point energized, SS1 de-energized':'Supply path energized through F1 and R1');
  for(const [prefix,status,bus,line] of [['f1',f,source,l1],['r1',r,remote,l2]]){
    const pos=position(status,stale),trip=stale?'UNKNOWN':status.tripped?`LATCHED · ${status.trip_reason||'unknown'}`:'CLEAR';
    put(prefix+'State',pos,pos==='CLOSED'?'good':pos==='OPEN'?'off':null);put(prefix+'Trip',trip,trip.startsWith('LATCHED')?'off':trip==='CLEAR'?'good':null);
    if(prefix==='f1')put('f1Alarm',stale?'UNKNOWN':status.undervoltage_alarm?'ACTIVE':'CLEAR',status.undervoltage_alarm&&!stale?'warn':'good');
    else put('r1Alarm',displayVoltage(bus,stale));
    const p=prefix==='f1'?'pf1':'pr1';put(p+'Position',pos);put(p+'Reason',stale?'UNKNOWN':status.trip_reason||'NONE');put(p+'Voltage',displayVoltage(bus,stale));put(p+'Current',displayCurrent(line,stale));
    setLamp(p+'ClosedLamp',pos==='CLOSED'?'good':null);setLamp(p+'OpenLamp',pos==='OPEN'?'off':null);setLamp(p+'TripLamp',!stale&&status.tripped?'off':null);
  }
  setLamp('pf1AlarmLamp',!stale&&f.undervoltage_alarm?'warn':null);
  document.querySelectorAll('button[data-breaker]').forEach(btn=>btn.disabled=stale);
}

async function getSnapshot(){try{const r=await fetch('/api/v1/snapshot',{cache:'no-store'});if(!r.ok)throw new Error('snapshot unavailable');snapshot=await r.json();lastSeen=Date.now();render(snapshot);}catch(_){if(snapshot)render(snapshot,true);else setConnection(false);}}
function showOutcome(e){
  if(!e.breaker)return;
  const id=e.breaker==='BRK_F1'?'f1Command':'r1Command';
  if(e.event==='POSITION_FEEDBACK')put(id,`${e.cause==='protection'?'Protection':'Remote'} ${e.requested_state} requested · actual ${e.actual_state} · ${e.success?'operation completed':'ACTUATION FAILED'}`,e.success?'good':'off');
  if(e.event==='CLOSE_REJECTED')put(id,'CLOSE rejected: trip latch active. RESET first.','off');
  if(e.event==='RESET')put(id,'Latch reset. Physical breaker position did not change.','good');
}
function onEvent(e){
  const extra=[e.requested_state,e.actual_state,e.success===false?'FAILED':e.success===true?'SUCCESS':null].filter(Boolean).join(' / ');
  put('latestEvent',`${e.ts} · ${e.ied||'SYSTEM'} · ${e.event} · ${e.breaker||''} ${extra}`);
  if(['POSITION_FEEDBACK','CLOSE_REJECTED','RESET'].includes(e.event)){
    showOutcome(e);
    if(e.request_id){completed.set(e.request_id,e);pending.delete(e.request_id);if(completed.size>100)completed.delete(completed.keys().next().value);}
  }else if(e.request_id&&pending.has(e.request_id)){
    const breaker=pending.get(e.request_id),id=breaker==='BRK_F1'?'f1Command':'r1Command';
    if(e.event==='OPERATION_REQUEST')put(id,'Operation accepted by IED. Awaiting physical position feedback…');
  }
  if(page==='engineeringPage'){clearTimeout(historyTimer);historyTimer=setTimeout(loadHistory,1300);}
}
function connect(){const source=new EventSource('/api/v1/stream');source.onmessage=message=>{try{const m=JSON.parse(message.data);if(m.kind==='snapshot'){snapshot=m.data;lastSeen=Date.now();render(snapshot);}else if(m.kind==='event')onEvent(m.data);else if(m.kind==='resync')getSnapshot();}catch(err){console.error(err);}};source.onerror=()=>{if(Date.now()-lastSeen>3000&&snapshot)render(snapshot,true);};}
document.querySelectorAll('button[data-breaker]').forEach(button=>button.addEventListener('click',async()=>{
  const breaker=button.dataset.breaker,action=button.dataset.action,id=breaker==='BRK_F1'?'f1Command':'r1Command';
  put(id,`${action} request being queued…`);
  try{const r=await fetch(`/api/v1/breakers/${breaker}/commands`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command:action})});const data=await r.json();if(!r.ok)throw new Error(data.error||'request failed');if(completed.has(data.request_id)){showOutcome(completed.get(data.request_id));completed.delete(data.request_id);}else{pending.set(data.request_id,breaker);put(id,`${action} queued (${data.request_id.slice(0,8)}). Awaiting scan result…`);}}catch(err){put(id,`Request failed: ${err.message}`,'off');}
}));

const getBus=(name,field,scale=1)=>s=>{const x=b(s,name);return x?.quality==='GOOD'&&finite(x[field])?x[field]*scale:null;};
const getLine=(name,field)=>s=>{const x=l(s,name);return x?.quality==='GOOD'&&finite(x[field])?x[field]:null;};
const getTrafo=(name,field)=>s=>{const x=t(s,name);return x?.quality==='GOOD'&&finite(x[field])?x[field]:null;};
function drawChart(id,rows,series,unit){
  const root=$(id);root.replaceChildren();if(!rows.length){root.innerHTML='<div class="empty">No stored samples in this range</div>';return;}
  const values=series.flatMap(x=>rows.map(s=>x.read(s)).filter(finite));if(!values.length){root.innerHTML='<div class="empty">Measurements unavailable in this range</div>';return;}
  const W=700,H=205,L=48,R=14,T=16,B=29,t0=Date.parse(rows[0].ts),t1=Math.max(Date.parse(rows.at(-1).ts),t0+1000);let lo=Infinity,hi=-Infinity;for(const value of values){lo=Math.min(lo,value);hi=Math.max(hi,value);}if(lo===hi){lo-=1;hi+=1;}const pad=(hi-lo)*.12;lo-=pad;hi+=pad;
  const x=ts=>L+(Date.parse(ts)-t0)/(t1-t0)*(W-L-R),y=v=>T+(hi-v)/(hi-lo)*(H-T-B);
  const svg=['<svg viewBox="0 0 700 205" role="img" aria-label="Time series">'];
  for(let i=0;i<5;i++){const yy=T+(H-T-B)*i/4,v=hi-(hi-lo)*i/4;svg.push(`<line x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}" stroke="#2c414a" stroke-width="1"/><text x="${L-7}" y="${yy+4}" fill="#91a6ae" text-anchor="end" font-size="10">${v.toFixed(Math.abs(v)<1?2:1)}</text>`);}
  svg.push(`<text x="${L}" y="${H-5}" fill="#91a6ae" font-size="10">${new Date(t0).toISOString().slice(11,16)} UTC</text><text x="${W-R}" y="${H-5}" fill="#91a6ae" text-anchor="end" font-size="10">${new Date(t1).toISOString().slice(11,16)} UTC</text>`);
  series.forEach((definition,i)=>{let segment=[];let previous=null;const flush=()=>{if(segment.length)svg.push(`<path d="${segment.join(' ')}" fill="none" stroke="${definition.color||colors[i%colors.length]}" stroke-width="2.3" stroke-linejoin="round" stroke-linecap="round"/>`);segment=[];};for(const row of rows){const val=definition.read(row),dt=previous?Date.parse(row.ts)-Date.parse(previous.ts):0;if(!finite(val)||previous&&(previous.run_id!==row.run_id||dt>1500||dt<0)){flush();}if(finite(val))segment.push(`${segment.length?'L':'M'}${x(row.ts).toFixed(1)} ${y(val).toFixed(1)}`);previous=row;}flush();});svg.push('</svg>');root.innerHTML=svg.join('');
  const legend=document.createElement('div');legend.className='legend-row';for(const [i,definition] of series.entries()){const span=document.createElement('span'),swatch=document.createElement('i');swatch.style.background=definition.color||colors[i%colors.length];span.append(swatch,document.createTextNode(`${definition.name} · ${unit}`));legend.append(span);}root.append(legend);
}
function drawTimeline(rows){
  const root=$('energizationTimeline');root.replaceChildren();
  if(!rows.length){root.innerHTML='<div class="empty">No stored topology in this range</div>';return;}
  const assets=[...busNames,'L1_FEEDER_HEAD','L2_FEEDER_TAIL','T1_PRIMARY','T2_SS1'];
  const W=900,L=165,R=20,H=assets.length*25+35,t0=Date.parse(rows[0].ts),t1=Math.max(Date.parse(rows.at(-1).ts),t0+1000);
  const x=ms=>L+(ms-t0)/(t1-t0)*(W-L-R);
  let svg=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Energization timeline">`;
  for(const [i,asset] of assets.entries()){
    const yy=7+i*25;
    svg+=`<text x="${L-8}" y="${yy+13}" text-anchor="end" fill="#a8bbc0" font-size="10">${asset}</text><line x1="${L}" y1="${yy+8}" x2="${W-R}" y2="${yy+8}" stroke="#263740" stroke-width="17"/>`;
    let start=null,end=null,color=null;
    const flush=()=>{if(start!==null)svg+=`<rect x="${x(start)}" y="${yy}" width="${Math.max(1,x(end)-x(start))}" height="17" fill="${color}"/>`;start=null;};
    for(let j=0;j<rows.length-1;j++){
      const a=rows[j],z=rows[j+1],am=Date.parse(a.ts),zm=Date.parse(z.ts),dt=zm-am;
      if(a.run_id!==z.run_id||dt>1500||dt<0){flush();continue;}
      const o=busNames.includes(asset)?b(a,asset):asset.startsWith('L')?l(a,asset):t(a,asset);
      const nextColor=o?.quality==='GOOD'?'#51ddb5':o?.quality==='NOT_ENERGIZED'?'#e68072':'#8a9aa1';
      if(start!==null&&nextColor!==color)flush();
      if(start===null){start=am;color=nextColor;}
      end=zm;
    }
    flush();
  }
  svg+=`<text x="${L}" y="${H-4}" fill="#91a6ae" font-size="10">${new Date(t0).toISOString().slice(11,16)} UTC</text><text x="${W-R}" y="${H-4}" fill="#91a6ae" text-anchor="end" font-size="10">${new Date(t1).toISOString().slice(11,16)} UTC</text></svg>`;
  root.innerHTML=svg;
}
function renderEvents(events){const body=$('eventRows');body.replaceChildren();if(!events.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=6;td.textContent='No events in this range';tr.append(td);body.append(tr);return;}for(const event of events.slice().reverse()){const tr=document.createElement('tr');const parts=[event.ts.replace('T',' ').replace('Z',' UTC'),event.ied||'SYSTEM',event.event,event.position||'—',event.tripped==null?'—':event.tripped?'LATCHED':'CLEAR',[event.requested_state&&`${event.requested_state} requested`,event.actual_state&&`actual ${event.actual_state}`,event.success===false&&'FAILED',event.cause].filter(Boolean).join(' · ')||'—'];for(const value of parts){const td=document.createElement('td');td.textContent=value;tr.append(td);}body.append(tr);}}
async function fetchPage(url){let cursor=null,items=[];for(let count=0;count<100;count++){const u=new URL(url,location.origin);if(cursor)u.searchParams.set('cursor',cursor);const r=await fetch(u);if(!r.ok)throw new Error(`${r.status} from ${u.pathname}`);const page=await r.json();items.push(...page.items);cursor=page.next_cursor;if(!cursor)break;}return items;}
async function loadHistory(){if(page!=='engineeringPage'||historyBusy)return;historyBusy=true;const minutes=Number($('rangeSelect').value),to=new Date(),from=new Date(to.getTime()-minutes*60_000),qs=`from=${encodeURIComponent(from.toISOString())}&to=${encodeURIComponent(to.toISOString())}&limit=10000`;put('historyInfo','Loading stored samples and scan events…');try{const [rows,events]=await Promise.all([fetchPage(`/api/v1/history?${qs}`),fetchPage(`/api/v1/events?${qs}`)]);put('historyInfo',`${rows.length.toLocaleString()} electrical/topology snapshots · ${events.length.toLocaleString()} scan events · ${from.toISOString()} to ${to.toISOString()}`);drawChart('chartPu',rows,busNames.map((name,i)=>({name:`${name} (${[110,20,20,20,.4][i]} kV base)`,read:getBus(name,'vm_pu')})),'p.u.');drawChart('chart110',rows,[{name:'GRID_110KV',read:getBus('GRID_110KV','vm_kv')}],'kV');drawChart('chart20',rows,['BUS_MV_SOURCE','BUS_R1_REMOTE','BUS_SS1_MV'].map(name=>({name,read:getBus(name,'vm_kv')})),'kV');drawChart('chart400',rows,[{name:'BUS_SS1_LV',read:getBus('BUS_SS1_LV','vm_kv',1000)}],'V');const lineNames=['L1_FEEDER_HEAD','L2_FEEDER_TAIL'];for(const [id,field,unit] of [['chartP','p_mw','MW'],['chartQ','q_mvar','MVAr'],['chartCurrent','i_ka','kA'],['chartLineLoading','loading_percent','%']])drawChart(id,rows,lineNames.map(name=>({name:`${name} · from`,read:getLine(name,field)})),unit);drawChart('chartTransformer',rows,['T1_PRIMARY','T2_SS1'].map(name=>({name,read:getTrafo(name,'loading_percent')})),'%');drawTimeline(rows);renderEvents(events);}catch(err){put('historyInfo',`History unavailable: ${err.message}`);}finally{historyBusy=false;}}
if(page==='engineeringPage'){$('rangeSelect').addEventListener('change',loadHistory);$('refreshHistory').addEventListener('click',loadHistory);setInterval(loadHistory,10000);loadHistory();}
let lastRecoveryPoll=0;
setInterval(()=>{if(snapshot&&Date.now()-lastSeen>3000){render(snapshot,true);if(Date.now()-lastRecoveryPoll>3000){lastRecoveryPoll=Date.now();getSnapshot();}}},1000);
getSnapshot();connect();

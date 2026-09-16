// Operations are serialized: the source event and exact closed sample must match.
// Timing starts BEFORE close HTTP, ends on the actual DOM, never on an API response.
const { chromium } = require('playwright');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { randomUUID } = require('node:crypto');
const base = process.argv[2] || 'http://localhost:8080';
const output = process.argv[3] || 'artifacts/acceptance/latency.json';
const selector = '[data-bankpulse-panel="integrity_percent"]';
function database(query) {
  return execFileSync('docker', ['compose','exec','-T','postgres','sh','-c',
    'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"','sh',query], {encoding:'utf8'}).trim();
}
function completionEvent(id) {
  const sql = `select event_id from social_split.social_split_outbox_events where aggregate_id='${id}' and event_type='SplitCompleted'`;
  // Only generated UUIDs enter this query; credentials remain in the container.
  if (!/^[a-f0-9-]{36}$/.test(id)) throw new Error('Unexpected session id');
  return database(sql);
}
(async () => {
  fs.mkdirSync(path.dirname(output), {recursive:true});
  const report = {measurementTarget:'grafana-render', requested:100, observed:0, lost:0, errors:[], samples:[],
    environment:{node:process.version,cpus:os.cpus().length,memoryBytes:os.totalmem(),platform:os.platform(),sha:execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),concurrency:1},
    method:'100 sequential complete sessions; timer before close request through DOM; ACTUAL normalized to FRESH; nearest-rank p95; failures retained at >= 10000ms'};
  const browser = await chromium.launch({headless:true});
  const page = await browser.newPage({locale:'en-US',viewport:{width:1440,height:1100}});
  async function api(endpoint, data) {
    const response = await page.request.post(base+'/api/splits'+endpoint,{data,timeout:10000});
    if (!response.ok()) throw new Error(`HTTP ${response.status()} ${endpoint}`);
    return response.json();
  }
  try {
    const login=await page.request.post('http://localhost:3000/login',{data:{user:'admin',password:'bankpulse_demo'}});
    if (!login.ok()) throw new Error('Grafana login failed');
    await page.goto('http://localhost:3000/d/bankpulse-deber-01');
    await page.waitForFunction(s=>document.querySelector(s)?.dataset.quality==='ACTUAL',selector,{timeout:60000});
    // Independent B-K3 oracle: existing OPEN sessions; each measured session
    // closes before rendering and therefore must not enter the OPEN cohort.
    const openSessions=JSON.parse(database(`select coalesce(json_agg(q),'[]') from (
      select extract(epoch from s.created_at)*1000+120000 as "deadlineMs",
        coalesce(sum(case when p.authorized then p.share_amount*100 else 0 end),0) as cents
      from social_split.split_sessions s left join social_split.split_participants p on p.session_id=s.id
      where s.status='OPEN' and s.currency='USD' group by s.id) q`));
    for(let i=0;i<100;i++) {
      const sample={index:i,correlationId:randomUUID(),rendered:false,correct:false,latencyMs:10000};
      let start;
      try {
        let session=await api('',{hostMemberId:sample.correlationId,totalAmount:100,currency:'USD'});
        const sid=session.id;
        for(const [member,share] of [['one',60],['two',40]]) session=await api(`/${sid}/participants`,{memberId:member,shareAmount:share});
        for(const p of session.participants) await api(`/${sid}/participants/${p.id}/authorize`,{paymentReference:sample.correlationId});
        const before=await page.locator(selector).evaluate(e=>({...e.dataset}));
        start=performance.now();
        const closed=await api(`/${sid}/close`,{});
        if(closed.status!=='COMPLETED') throw new Error('close did not complete');
        const renderedHandle=await page.waitForFunction(({s,b,opens})=>{
          const e=document.querySelector(s), gap=document.querySelector('[data-bankpulse-panel="closure_gap"]');
          const stale=document.querySelector('[data-bankpulse-panel="stale_authorized"]');
          const expectedCents=opens.filter(x=>Date.now()>Number(x.deadlineMs)).reduce((sum,x)=>sum+Number(x.cents),0);
          return e?.dataset.quality==='ACTUAL' && Number(e.dataset.sample)===Number(b.sample)+1 &&
            e.dataset.eventId!==b.eventId && Number(e.dataset.value)===100 && e.textContent.includes('100%') &&
            gap?.dataset.quality==='ACTUAL' && Number(gap.dataset.value)===0 && gap.dataset.eventId===e.dataset.eventId && gap.textContent.includes('USD 0') &&
            stale?.dataset.quality==='ACTUAL' && Math.round(Number(stale.dataset.value)*100)===expectedCents && stale.dataset.eventId===e.dataset.eventId &&
            {integrity:{...e.dataset},gap:{...gap.dataset},stale:{...stale.dataset},expectedStaleCents:expectedCents};
        },{s:selector,b:before,opens:openSessions},{timeout:10000,polling:'raf'});
        sample.latencyMs=performance.now()-start;
        const panels=await renderedHandle.jsonValue();
        const rendered=panels.integrity;
        const expectedEventId=completionEvent(sid);
        if(!expectedEventId || rendered.eventId!==expectedEventId) throw new Error('Rendered event does not match persisted completion');
        Object.assign(sample,{panels,sessionId:sid,eventId:expectedEventId,rendered:true,correct:true,quality:'FRESH',panelQuality:rendered.quality,revision:Number(rendered.revision),closedSample:Number(rendered.sample)});
        report.observed++;
      } catch(e) {
        sample.latencyMs=Math.max(10000,start?performance.now()-start:0);
        sample.error=String(e); report.errors.push({index:i,error:String(e)}); report.lost++;
      }
      report.samples.push(sample);
      console.log(JSON.stringify(sample));
    }
    await page.screenshot({path:path.join(path.dirname(output),'benchmark.png'),fullPage:true});
  } catch(e) {report.errors.push({error:String(e)});throw e;}
  finally {
    const sorted=report.samples.map(s=>s.latencyMs).sort((a,b)=>a-b);
    report.maximumMs=sorted.at(-1)??null; report.p50Ms=sorted[49]??null; report.p95Ms=sorted[94]??null;
    report.lost=100-report.observed;
    fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n');
    await browser.close();
  }
  if(report.observed!==100 || report.errors.length || report.p95Ms>1000) throw new Error(`Benchmark failed: observed=${report.observed} p95=${report.p95Ms}`);
})().catch(e=>{console.error(e);process.exitCode=1});

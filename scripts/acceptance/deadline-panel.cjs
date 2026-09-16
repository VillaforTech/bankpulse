// Observe the unaccelerated 120-second business deadline with no new operations.
const { chromium } = require('playwright');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const { randomUUID } = require('node:crypto');
(async()=>{
  const browser=await chromium.launch({headless:true});
  const output='artifacts/acceptance/deadline.json';
  let report={result:'FAIL',deadlineSeconds:120};
  try {
    const page=await browser.newPage({locale:'en-US',viewport:{width:1440,height:1100}});
    async function api(path,data){
      const response=await page.request.post('http://localhost:8080/api/splits'+path,{data});
      if(!response.ok())throw new Error('API '+response.status());
      return response.json();
    }
    const login=await page.request.post('http://localhost:3000/login',{data:{user:'admin',password:'bankpulse_demo'}});
    if(!login.ok())throw new Error('Login failed');
    await page.goto('http://localhost:3000/d/bankpulse-deber-01');
    const selector='[data-bankpulse-panel="stale_authorized"]';
    await page.waitForFunction(s=>document.querySelector(s)?.dataset.quality==='ACTUAL',selector,{timeout:60000});
    let session=await api('',{hostMemberId:randomUUID(),totalAmount:100,currency:'USD'});
    session=await api(`/${session.id}/participants`,{memberId:'waiting',shareAmount:60});
    session=await api(`/${session.id}/participants/${session.participants[0].id}/authorize`,{paymentReference:'deadline-demo'});
    // All other OPEN sessions predate this one, so all their deadlines precede ours.
    const query="select coalesce(sum(p.share_amount),0) from social_split.split_participants p join social_split.split_sessions s on s.id=p.session_id where s.status='OPEN' and s.currency='USD' and p.authorized";
    const expected=Number(execFileSync('docker',['compose','exec','-T','postgres','sh','-c','exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"','sh',query],{encoding:'utf8'}).trim());
    const eventQuery=`select event_id from social_split.social_split_outbox_events where aggregate_id='${session.id}' and event_type='ParticipantAuthorized'`;
    const eventId=execFileSync('docker',['compose','exec','-T','postgres','sh','-c','exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"','sh',eventQuery],{encoding:'utf8'}).trim();
    await page.waitForFunction(({s,id})=>document.querySelector(s)?.dataset.eventId===id,{s:selector,id:eventId},{timeout:30000});
    const before=Number(await page.locator(selector).getAttribute('data-value'));
    if(!(expected>=60 && before<=expected-60))throw new Error('Premature expiry or invalid independent sum');
    const started=performance.now();
    const remaining=Date.parse(session.createdAt)+120000-Date.now();
    if(remaining<=0)throw new Error('Setup exceeded deadline');
    await page.waitForFunction(({s,total,id})=>{
      const e=document.querySelector(s);
      return e?.dataset.quality==='ACTUAL' && Number(e.dataset.value)===total && e.dataset.eventId===id && e.textContent.includes('ALERTA ACTIVA');
    },{s:selector,total:expected,id:eventId},{timeout:remaining+10000,polling:'raf'});
    const delayMs=performance.now()-started-remaining;
    report={...report,sessionId:session.id,eventId,before,expected,delayMs,method:'120s production rule; no new domain operations; independent sum of authorized OPEN USD shares; same runner wall clock anchored to monotonic elapsed time'};
    await page.screenshot({path:'artifacts/acceptance/deadline.png',fullPage:true});
    if(delayMs<0 || delayMs>1000)throw new Error('Deadline-to-render exceeded 1 second: '+delayMs);
    report.result='PASS';
  } catch(e){report.error=String(e);throw e;}
  finally {fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n');await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});

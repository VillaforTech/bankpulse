const { chromium } = require('playwright');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
(async () => {
  fs.mkdirSync('artifacts/live', {recursive:true});
  const browser = await chromium.launch({headless:true});
  const page = await browser.newPage({locale:'en-US',viewport:{width:1440,height:1100}});
  const diagnostics=[];
  page.on('pageerror', e=>diagnostics.push(String(e)));
  page.on('console', m=>{if(m.type()==='error')diagnostics.push(m.text())});
  try {
    const login=await page.request.post('http://localhost:3000/login',{data:{user:'admin',password:'bankpulse_demo'}});
    if(!login.ok()) throw new Error('Grafana login failed '+login.status());
    await page.goto('http://localhost:3000/d/bankpulse-deber-01');
    const selector = '[data-bankpulse-panel="integrity_percent"]';
    await page.waitForFunction(s => document.querySelector(s)?.dataset.quality === 'ACTUAL', selector, {timeout:60000});
    const before = await page.locator(selector).getAttribute('data-revision');
    execFileSync('python3',['scripts/analytics-integration.py'],{stdio:'inherit'});
    const expected=JSON.parse(fs.readFileSync('artifacts/analytics-integration.json')).snapshot;
    await page.waitForFunction(({s,r}) => Number(document.querySelector(s)?.dataset.revision)>Number(r) && document.querySelector(s)?.textContent.includes('100'),{s:selector,r:before},{timeout:30000});
    await page.waitForFunction(({s,event}) => document.querySelector(s)?.dataset.eventId===event,{s:selector,event:expected.lastEventId},{timeout:30000});
    await page.screenshot({path:'artifacts/live/healthy.png',fullPage:true});
    execFileSync('docker',['compose','-f','observability/compose.yaml','stop','grafana-live-adapter'],{stdio:'inherit'});
    await page.waitForFunction(s => document.querySelector(s)?.dataset.quality === 'DESACTUALIZADO',selector,{timeout:10000});
    await page.screenshot({path:'artifacts/live/stale.png',fullPage:true});
    execFileSync('docker',['compose','-f','observability/compose.yaml','start','grafana-live-adapter'],{stdio:'inherit'});
    await page.waitForFunction(s => document.querySelector(s)?.dataset.quality === 'ACTUAL',selector,{timeout:30000});
    await page.screenshot({path:'artifacts/live/recovered.png',fullPage:true});
    fs.writeFileSync('artifacts/live/result.json',JSON.stringify({result:'PASS',scope:'real producer, rendered KPI, stale state and same-page recovery; not the 100-render benchmark'}));
  } catch(e) {
    await page.screenshot({path:'artifacts/live/failure.png',fullPage:true});
    fs.writeFileSync('artifacts/live/diagnostics.json',JSON.stringify({errors:diagnostics,body:await page.locator('body').innerText()},null,2));
    throw e;
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exit(1)});

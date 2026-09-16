const { chromium } = require('playwright');
(async()=>{
  const browser=await chromium.launch({headless:true});
  try {
    const page=await browser.newPage({locale:'en-US',viewport:{width:1440,height:1100}});
    const response=await page.request.post('http://localhost:3000/login',{data:{user:'admin',password:'bankpulse_demo'}});
    if(!response.ok())throw new Error('Login failed');
    await page.goto('http://localhost:3000/d/bankpulse-deber-01');
    await page.waitForFunction(()=>{
      const integrity=document.querySelector('[data-bankpulse-panel="integrity_percent"]');
      const gap=document.querySelector('[data-bankpulse-panel="closure_gap"]');
      return integrity?.dataset.quality==='ACTUAL' && Number(integrity.dataset.value)<100 &&
        gap?.dataset.quality==='ACTUAL' && Number(gap.dataset.value)>=10 &&
        integrity.textContent.includes('ALERTA ACTIVA') && gap.textContent.includes('ALERTA ACTIVA');
    },undefined,{timeout:30000});
    await page.screenshot({path:'artifacts/acceptance/false-green/breach.png',fullPage:true});
    await page.context().setOffline(true);
    await page.waitForFunction(()=>document.querySelector('[data-bankpulse-panel="integrity_percent"]')?.dataset.quality==='DESACTUALIZADO',undefined,{timeout:10000});
    await page.context().setOffline(false);
    await page.waitForFunction(()=>document.querySelector('[data-bankpulse-panel="integrity_percent"]')?.dataset.quality==='ACTUAL',undefined,{timeout:45000});
    await page.screenshot({path:'artifacts/acceptance/false-green/reconnected.png',fullPage:true});
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});

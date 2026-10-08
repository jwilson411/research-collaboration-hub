// Supplemental first-use/recovery checks against an already-running disposable loopback demo.
// Run after browser-smoke.mjs; set HUB_FIRST_USE_MODE=restore after offline backup/restore.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
const require=createRequire(import.meta.url),{chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const base=process.env.HUB_BROWSER_URL||'http://127.0.0.1:5080';
assert(['127.0.0.1','localhost','[::1]'].includes(new URL(base).hostname));
const output=process.env.HUB_BROWSER_ARTIFACTS||'artifacts/browser-smoke';await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE,args:process.env.BROWSER_NO_SANDBOX==='true'?['--no-sandbox']:[]});
const context=await browser.newContext({viewport:{width:390,height:844}}),page=await context.newPage();
context.setDefaultTimeout(15000);
const errors=[],external=[];page.on('pageerror',e=>errors.push(e.message));context.on('request',r=>{if(new URL(r.url()).origin!==new URL(base).origin)external.push(r.url());});
const ready=async()=>page.getByRole('heading',{name:'My studies',exact:true}).waitFor();
const identity=async id=>{await page.locator('#identity').selectOption(id);await ready();await page.getByText('Demo identity changed. Accessible studies have been refreshed.',{exact:false}).waitFor();};
const json=async path=>{const r=await context.request.get(base+path);assert.equal(r.status(),200);return r.json();};
try{
 await page.goto(base);await ready();
 if(process.env.HUB_FIRST_USE_MODE!=='restore'){
  const nojs=await browser.newContext({javaScriptEnabled:false});nojs.setDefaultTimeout(15000);const p=await nojs.newPage();await p.goto(base);await p.getByRole('heading',{name:'JavaScript is required for this local preview'}).waitFor();assert.equal(await p.locator('#identity').isVisible(),false);assert(!await p.locator('main').innerText().then(t=>t.includes('Loading')));await nojs.close();
  const loading=await browser.newContext();loading.setDefaultTimeout(15000);const lp=await loading.newPage();let release;const gate=new Promise(r=>release=r);await lp.route('**/api/session',async route=>{await gate;await route.continue();});await lp.goto(base,{waitUntil:'domcontentloaded'});await lp.getByText('Loading your accessible study workspace…',{exact:true}).waitFor();release();await lp.getByRole('heading',{name:'My studies',exact:true}).waitFor();await loading.close();
  const failed=await browser.newContext();failed.setDefaultTimeout(15000);const fp=await failed.newPage();await fp.route('**/api/session',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({message:'Synthetic startup interruption'})}));await fp.goto(base);await fp.getByRole('heading',{name:'Unable to load the local demo'}).waitFor();await fp.unroute('**/api/session');await fp.reload();await fp.getByRole('heading',{name:'My studies',exact:true}).waitFor();await failed.close();
  await page.locator('#search').fill('unmatched-synthetic-first-use-query');await page.locator('#search-form button').click();await page.getByRole('heading',{name:'No matching records'}).waitFor();
  for(const kind of ['search','route']){
   let releaseRace,handledRace;const gateRace=new Promise(r=>releaseRace=r),finishedRace=new Promise(r=>handledRace=r);const pattern=kind==='search'?'**/api/search?**':'**/api/studies/atlas';let intercepted;const seen=new Promise(r=>intercepted=r);
   await page.route(pattern,async route=>{intercepted();await gateRace;try{await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({message:'Obsolete synthetic failure'})});}catch(error){if(!/already handled|aborted/i.test(error.message))throw error;}finally{handledRace();}});
   if(kind==='search'){await page.locator('#search').fill('Handoff');await page.locator('#search-form button').click();}else await page.goto(base+'/#study/atlas/overview');
   await seen;await identity('admin');await page.getByRole('heading',{name:'No study access'}).waitFor();releaseRace();await finishedRace;await page.unroute(pattern);await page.waitForTimeout(100);assert(!await page.locator('main').innerText().then(t=>t.includes('Obsolete synthetic failure')));await identity('alex');
  }
  const preRevocation=await json('/api/studies/atlas');
  const adminContext=await browser.newContext();adminContext.setDefaultTimeout(15000);const admin=await adminContext.newPage();await admin.goto(base);await admin.getByRole('heading',{name:'My studies',exact:true}).waitFor();await admin.locator('#identity').selectOption('admin');await admin.getByRole('heading',{name:'No study access'}).waitFor();await admin.getByRole('link',{name:'Administration',exact:true}).click();await admin.getByRole('heading',{name:'Access & configuration'}).waitFor();
  const mapping=async group=>{await admin.getByLabel('Stable group identifier',{exact:true}).fill(group);const old=await admin.locator('#mapping-form').getAttribute('data-revision');await admin.getByRole('button',{name:'Save mapping',exact:true}).click();await admin.waitForFunction(old=>document.querySelector('#mapping-form')?.dataset.revision!==old,old);};
  await mapping('demo-group-b');await page.reload();await page.getByRole('heading',{name:'No study access'}).waitFor();assert.equal((await context.request.get(base+'/api/studies/atlas')).status(),404);for(const file of preRevocation.files)assert.equal((await context.request.get(base+'/api/studies/atlas/files/'+file.id+'/download')).status(),404);await mapping('demo-group-a');await adminContext.close();
  await page.goto(base+'/#study/atlas/document/journey-guide-v1');await page.locator('#record-journey-guide-v1').waitFor();assert.equal(await page.locator(':focus').getAttribute('id'),'record-journey-guide-v1');assert(await page.locator('#record-journey-guide-v1').isVisible());
  await page.goto(base+'/#study/beacon/overview');await page.getByRole('heading',{name:'Workspace unavailable'}).waitFor();await identity('sam');await page.getByRole('link',{name:'Open workspace'}).click();await page.getByRole('link',{name:'Activity & lifecycle',exact:true}).click();await page.getByLabel('Workspace stage',{exact:true}).selectOption('Active');await page.getByRole('button',{name:'Update stage',exact:true}).click();await page.getByText('Saved. The shared record has been updated.',{exact:true}).waitFor();await identity('alex');
 }
 const study=await json('/api/studies/atlas');const snapshots=await json('/api/studies/atlas/handoffs');
 await identity('sam');const beacon=await json('/api/studies/beacon');assert.equal(beacon.stage,'Active');await identity('alex');
 const evidence={study,snapshots,beacon,details:[],files:[]};
 const historicalFile=study.files.find(f=>f.name==='synthetic-protocol-v1.txt');assert(historicalFile);await page.goto(base+'/#study/atlas/document/'+historicalFile.id);await page.locator('#record-'+historicalFile.id).waitFor();assert.equal(await page.locator(':focus').getAttribute('id'),'record-'+historicalFile.id);
 if(process.env.HUB_BROWSER_AXE==='true'){const AxeBuilder=require('@axe-core/playwright').default;assert.deepEqual((await new AxeBuilder({page}).analyze()).violations,[]);console.log('AXE: retained document/file history — 0 violations');}
 for(const snapshot of snapshots)evidence.details.push(await json('/api/studies/atlas/handoffs/'+snapshot.id));
 for(const file of study.files.filter(f=>f.status==='Released'||f.releaseState==='Released'||f.scanStatus==='DemoReleased')){const r=await context.request.get(base+'/api/studies/atlas/files/'+file.id+'/download');if(r.status()===200)evidence.files.push({id:file.id,sha256:createHash('sha256').update(await r.body()).digest('hex')});}
 // Recognize released files by successful server authorization, independent of display schema.
 if(!evidence.files.length)for(const file of study.files){const r=await context.request.get(base+'/api/studies/atlas/files/'+file.id+'/download');if(r.status()===200)evidence.files.push({id:file.id,sha256:createHash('sha256').update(await r.body()).digest('hex')});}
 assert(evidence.files.length>0,'The full journey must create downloadable synthetic evidence');assert(snapshots.length>1,'The full journey must capture a new handoff');
 if(process.env.HUB_FIRST_USE_MODE==='restore')assert.deepEqual(evidence,JSON.parse(await readFile(output+'/recovery-evidence.json','utf8')));else await writeFile(output+'/recovery-evidence.json',JSON.stringify(evidence));
 await page.goto(base+'/#study/atlas/overview');await page.getByRole('heading',{name:'At a glance'}).waitFor();assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),390);await page.screenshot({path:output+'/first-use-restorable-mobile.png',fullPage:true});
 assert.deepEqual(errors,[]);assert.deepEqual(external,[]);console.log('PASS: '+(process.env.HUB_FIRST_USE_MODE==='restore'?'restored exact study, handoffs, file hashes and mobile overview':'no-JS, loading, interrupted startup recovery, empty search, delayed search/route errors across identities, historical disclosure focus, access isolation, Beacon reopen; recorded restore evidence'));
}finally{await browser.close();}

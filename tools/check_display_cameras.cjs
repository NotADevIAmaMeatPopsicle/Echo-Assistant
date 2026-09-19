const {previewBase}=require('./display_check.cjs');
/* Synthetic preview only: no real cameras, home actions or audio. */
const {chromium}=require('playwright');const assert=require('node:assert/strict');
(async()=>{
  const base=await previewBase();const browser=await chromium.launch({channel:'chrome',headless:true});try{
 const page=await browser.newPage({viewport:{width:1024,height:600}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));await page.route('**/*',r=>new URL(r.request().url()).hostname==='127.0.0.1'?r.continue():r.abort());
 await page.addInitScript(()=>{HTMLMediaElement.prototype.play=()=>{throw Error('No audio in camera check');};});
 await page.goto(base+'/display#settings');await page.locator('#source-load').click();
 await page.locator('[data-ring-trigger]').check();await page.locator('[data-ring-label]').fill('Front door');await page.locator('[data-ring-camera]').selectOption('camera.porch_demo');
 await page.locator('#source-form button[type=submit]').click();await page.waitForFunction(()=>!document.getElementById('source-form').querySelector('button[type=submit]').disabled);
 await page.locator('nav [data-page=day]').click();await page.locator('#camera-choice').selectOption('camera.porch_demo');await page.locator('#camera-open:not([disabled])').click();
 await page.waitForFunction(()=>document.getElementById('camera-status').textContent.startsWith('Live ·'));
 const first=await page.locator('#camera-frame').getAttribute('src');await page.waitForFunction(x=>document.getElementById('camera-frame').src!==x,first);
 await page.locator('#toast').waitFor({state:'hidden'});await page.locator('.camera-card').scrollIntoViewIfNeeded();await page.screenshot({path:'output/playwright/display-camera-live.png'});
 await page.locator('#camera-close').click();assert.ok(await page.locator('#camera-frame').isHidden());assert.equal(await page.locator('#camera-frame').getAttribute('src'),null);
 await page.locator('#camera-mode').selectOption('snapshots');await page.locator('#camera-open:not([disabled])').click();await page.waitForFunction(()=>document.getElementById('camera-status').textContent.startsWith('Latest snapshot'));
 await page.locator('nav [data-page=home]').click();assert.equal(await page.locator('#camera-frame').getAttribute('src'),null);
 const ring=await page.request.post(base+'/v1/demo/doorbell',{data:{}});assert.equal(ring.status(),200);
 await page.locator('#doorbell-banner').waitFor({state:'visible'});assert.equal(await page.locator('#camera-frame').getAttribute('src'),null);
 await page.screenshot({path:'output/playwright/display-doorbell.png'});
 await page.locator('#ambient-button').click();await page.locator('#doorbell-banner [data-ring-view]').click();assert.ok(await page.locator('#ambient').isHidden());await page.waitForFunction(()=>document.getElementById('camera-status').textContent.startsWith('Live ·'));
 await page.locator('#camera-close').click();await page.locator('#doorbell-events [data-ring-dismiss]').click();await page.waitForFunction(()=>!document.querySelector('#doorbell-events [data-ring-dismiss]'));
 await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 assert.deepEqual(errors,[]);console.log('Moving MJPEG frames, snapshots, close/navigation abort, opt-in binding, silent ring, explicit camera open and dismissal passed.');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});

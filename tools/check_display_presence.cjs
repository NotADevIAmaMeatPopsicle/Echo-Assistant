/* Synthetic presence only. Never calls Home Assistant or opens a microphone. */
const {previewBase}=require('./display_check.cjs');
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
  const base=await previewBase(),browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1024,height:600},hasTouch:true}),errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/v1/display/screen',r=>r.fulfill({json:{supported:false}}));
    await page.clock.install();await page.goto(base+'/display#settings');
    await page.locator('#source-load').click();
    await page.locator('#source-presence input').check();
    await page.locator('#source-form button[type=submit]').click();
    await page.waitForFunction(async()=>{
      const s=await (await fetch('/v1/display/source-settings')).json();
      return s.sources.presence_sensors?.length===1;
    });
    const saved=await page.evaluate(async()=>(await (await fetch('/v1/display/source-settings')).json()).sources);
    assert.deepEqual(saved.presence_sensors,['binary_sensor.study_demo']);
    assert.deepEqual(saved.calendars,['calendar.household_demo']);
    assert.deepEqual(saved.cameras,['camera.porch_demo']);
    assert.deepEqual(saved.writable_calendars,['calendar.household_demo']);
    let occupied=false,available=true,revoked=false,offline=false;
    await page.route('**/v1/display/presence',r=>r.fulfill({status:offline?503:200,json:{status:'available',items:revoked?[]:[{entity_id:'binary_sensor.study_demo',name:'Study occupancy · sample',available,occupied:available?occupied:null}]}}));
    async function poll(){
      await Promise.all([page.waitForResponse(r=>new URL(r.url()).pathname==='/v1/display/presence'),page.clock.fastForward(5000)]);
      await page.waitForTimeout(50);
    }
    await poll();
    assert.equal(await page.locator('#screen-presence').inputValue(),'');
    await page.locator('#screen-presence').selectOption('binary_sensor.study_demo');
    await page.locator('#screen-dim').selectOption('60');await page.locator('#screen-off').selectOption('120');
    await page.locator('#screen-form button[type=submit]').click();
    await page.reload();await page.locator('#screen-presence option[value="binary_sensor.study_demo"]').waitFor({state:'attached'});
    assert.equal(await page.locator('#screen-presence').inputValue(),'binary_sensor.study_demo');
    await page.clock.fastForward(121000);assert.equal(await page.locator('#screen-cover').getAttribute('data-mode'),'sleep');
    occupied=true;await poll();assert.equal(await page.locator('#screen-cover').getAttribute('data-mode'),'awake');
    await page.locator('#screen-sleep-now').click();await poll();
    assert.equal(await page.locator('#screen-cover').getAttribute('data-mode'),'sleep');
    occupied=false;await poll();assert.equal(await page.locator('#screen-cover').getAttribute('data-mode'),'sleep');
    occupied=true;await poll();assert.equal(await page.locator('#screen-cover').getAttribute('data-mode'),'awake');
    // An unavailable sensor cannot keep a screen awake or invent a clear event.
    available=false;await poll();await page.clock.fastForward(121000);
    assert.equal(await page.locator('#screen-cover').getAttribute('data-mode'),'sleep');
    available=true;occupied=true;await poll();assert.equal(await page.locator('#screen-cover').getAttribute('data-mode'),'awake');
    offline=true;await poll();await page.clock.fastForward(121000);
    assert.equal(await page.locator('#screen-cover').getAttribute('data-mode'),'sleep');
    offline=false;revoked=true;await poll();assert.equal(await page.locator('#screen-cover').getAttribute('data-mode'),'sleep');
    await page.touchscreen.tap(43,150);assert.equal(await page.locator('#screen-cover').getAttribute('data-mode'),'awake');
    assert.equal(new URL(page.url()).hash,'#settings');
    await page.locator('#screen-presence').selectOption('');await page.locator('#screen-dim').focus();await poll();
    assert.equal(await page.locator('#screen-presence').inputValue(),''); // Preserve an unsaved Off choice.
    await page.locator('#screen-form button[type=submit]').click();
    revoked=false;await poll();await page.clock.fastForward(121000);
    assert.equal(await page.locator('#screen-cover').getAttribute('data-mode'),'sleep');
    assert.deepEqual(errors,[]);
    console.log('PASS: source grants preserve existing selections; per-display presence persistence, wake, manual sleep, unavailable/offline/revoked states and disabling.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

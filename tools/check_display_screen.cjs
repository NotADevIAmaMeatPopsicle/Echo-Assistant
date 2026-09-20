/* Synthetic timers and touch events only; never talks to a real screen or room. */
const {previewBase}=require('./display_check.cjs');
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
  const base=await previewBase(),browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const context=await browser.newContext({viewport:{width:1024,height:600},hasTouch:true});
    const page=await context.newPage(),errors=[],writes=[];
    page.on('pageerror',e=>errors.push(e.message));
    page.on('request',r=>{if(r.method()!=='GET'&&new URL(r.url()).pathname.startsWith('/v1/'))writes.push(r.url());});
    await page.route('**/v1/display/screen',r=>r.fulfill({json:{supported:false}}));
    await page.clock.install();await page.goto(base+'/display#home');
    await page.locator('#home-music-title').filter({hasText:'Room to breathe'}).waitFor();
    await page.clock.fastForward(121000);
    assert.equal(await page.locator('#screen-cover').getAttribute('data-mode'),'dim');
    await page.clock.fastForward(480000);
    assert.equal(await page.locator('#screen-cover').getAttribute('data-mode'),'sleep');
    // Tap directly over a real control. It must wake only, without navigation.
    await page.touchscreen.tap(43,150);
    assert.equal(await page.locator('#screen-cover').getAttribute('data-mode'),'awake');
    assert.equal(new URL(page.url()).hash,'#home');
    await page.locator('nav [data-page=rooms]').tap();assert.equal(new URL(page.url()).hash,'#rooms');
    await page.locator('.rail-settings').tap();
    await page.locator('#screen-dim').selectOption('300');await page.locator('#screen-off').selectOption('60');
    await page.locator('#screen-form [type=submit]').tap();
    assert.match(await page.locator('#screen-message').textContent(),/later/);
    await page.locator('#screen-dim').selectOption('0');await page.locator('#screen-off').selectOption('0');
    await page.locator('#screen-form [type=submit]').tap();await page.reload();
    await page.locator('.rail-settings').tap();assert.equal(await page.locator('#screen-off').inputValue(),'0');
    await page.clock.fastForward(601000);assert.equal(await page.locator('#screen-cover').getAttribute('data-mode'),'awake');
    if(await page.locator('#ambient').isVisible())await page.locator('#wake-screen').tap();
    await page.locator('#screen-sleep-now').tap();await page.clock.fastForward(5000);
    assert.equal(await page.locator('#screen-cover').getAttribute('data-mode'),'sleep');
    await page.keyboard.press('Space');assert.equal(await page.locator('#screen-cover').getAttribute('data-mode'),'awake');
    // A live assistant conversation keeps the display awake, including native wake.
    await page.evaluate(()=>{chatAbort={};});
    await page.locator('#screen-sleep-now').tap();await page.clock.fastForward(1000);
    assert.equal(await page.locator('#screen-cover').getAttribute('data-mode'),'awake');
    assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
    console.log('PASS: idle dim/sleep, wake-only first tap, keyboard wake, disabled timers, persistence, validation and voice wake.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

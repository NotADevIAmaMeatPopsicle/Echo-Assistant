/* Exercise the personal layout and actual touch navigation using synthetic state. */
const {previewBase}=require('./display_check.cjs');
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
  const base=await previewBase(),browser=await chromium.launch({channel:'chrome',headless:true});
  try {
    const context=await browser.newContext({viewport:{width:1024,height:600},hasTouch:true});
    const page=await context.newPage(),errors=[],writes=[];
    page.on('pageerror',e=>{errors.push(e.message);console.error(e.stack);});
    page.on('request',r=>{if(r.method()!=='GET'&&new URL(r.url()).pathname.startsWith('/v1/'))writes.push(r.url());});
    await page.goto(base+'/display#home');
    await page.locator('#home-music-title').filter({hasText:'Room to breathe'}).waitFor();
    const layout=()=>page.locator('.home-grid>[data-home-slot]').evaluateAll(nodes=>nodes.map(n=>n.dataset.homeTile));
    assert.deepEqual(await layout(),['clock','weather','rooms','music']);
    const bounds=await page.locator('[data-home-tile=music]').boundingBox();
    assert.ok(bounds.x>650 && bounds.y>300 && bounds.y+bounds.height<=568,JSON.stringify(bounds));
    fs.mkdirSync('output/playwright',{recursive:true});
    await page.screenshot({path:'output/playwright/display-home-custom.png',animations:'disabled'});
    const dialog=page.locator('#home-tile-dialog');
    await page.locator('#edit-home').tap();await dialog.waitFor({state:'visible'});
    await page.locator('[data-home-slot-choice="3"]').tap();await page.locator('[data-home-choice=timers]').tap();
    await page.screenshot({path:'output/playwright/display-home-picker.png',animations:'disabled'});
    await page.locator('#home-tiles-cancel').tap();assert.deepEqual(await layout(),['clock','weather','rooms','music']);
    await page.locator('#edit-home').tap();await page.locator('[data-home-slot-choice="1"]').tap();
    await page.locator('[data-home-choice=clock]').tap(); // Existing choice swaps, rather than disappearing.
    await page.locator('[data-home-slot-choice="3"]').tap();await page.locator('[data-home-choice=climate]').tap();
    await page.locator('#home-tiles-save').tap();assert.deepEqual(await layout(),['weather','clock','rooms','climate']);
    await page.reload();await page.locator('#home-climate-temp').filter({hasText:'21.5'}).waitFor();
    assert.deepEqual(await layout(),['weather','clock','rooms','climate']);
    // Updating unrelated display preferences preserves the tile layout.
    await page.locator('.rail-settings').tap();await page.locator('#clock24').check();
    await page.locator('#edit-home-settings').tap();await page.locator('[data-home-slot-choice="1"]').tap();
    await page.locator('[data-home-choice=empty]').tap();await page.locator('[data-home-slot-choice="2"]').tap();
    await page.locator('[data-home-choice=lists]').tap();await page.locator('#home-tiles-save').tap();
    await page.locator('nav [data-page=home]').tap();assert.deepEqual(await layout(),['weather','lists','climate']);
    await page.locator('#edit-home').tap();await page.locator('#home-tiles-reset').tap();await page.locator('#home-tiles-save').tap();
    assert.deepEqual(await layout(),['clock','weather','rooms','music']);
    const cdp=await context.newCDPSession(page);
    async function swipe(selector,dx,dy=0,cancel=false){
      const b=await page.locator(selector).boundingBox(),x=b.x+b.width/2,y=b.y+b.height/2;
      await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y}]});
      for(let i=1;i<=8;i++)await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:x+dx*i/8,y:y+dy*i/8}]});
      await cdp.send('Input.dispatchTouchEvent',{type:cancel?'touchCancel':'touchEnd',touchPoints:[]});
      await page.waitForTimeout(220);
    }
    const current=()=>new URL(page.url()).hash;
    await swipe('#home-clock',-180);assert.equal(current(),'#rooms');
    await swipe('#room-cards h2 >> nth=1',-180);assert.equal(current(),'#music');
    await swipe('#track-title',180);assert.equal(current(),'#rooms');
    await swipe('#room-cards h2 >> nth=1',180);assert.equal(current(),'#home');
    await swipe('#home-clock',180);assert.equal(current(),'#home','No wrap past Home');
    await swipe('#home-clock',25);assert.equal(current(),'#home');
    await swipe('#home-clock',5,100);assert.equal(current(),'#home','Vertical scrolling is not navigation');
    await swipe('#home-clock',-180,0,true);assert.equal(current(),'#home','Cancellation never navigates');
    await page.locator('#edit-home').tap();await swipe('#home-tile-heading',-160);assert.equal(current(),'#home');
    await page.locator('#home-tiles-cancel').tap();
    await page.locator('nav [data-page=music]').tap();await page.locator('#track-seek:not([disabled])').waitFor();
    // Slider input owns the gesture. Intercept the resulting media command.
    await page.route('**/v1/display/music/control',r=>r.fulfill({json:{accepted:true}}));
    await swipe('#track-seek',-100);assert.equal(current(),'#music','Seeking must not switch pages');
    await page.locator('nav [data-page=assistant]').tap();await page.locator('#chat-text').tap();
    await swipe('[data-letter=h]',-90);assert.equal(current(),'#assistant','Glide typing must not switch pages');
    await page.locator('[data-key-action=hide]').tap();
    await page.locator('.rail-settings').tap();await swipe('#page-settings h2 >> nth=1',-180);assert.equal(current(),'#settings');
    assert.ok(writes.every(url=>url.endsWith('/v1/display/music/control')),JSON.stringify(writes));
    await page.setViewportSize({width:390,height:844});await page.goto(base+'/display?layout-test=phone#home');
    await page.locator('[data-home-tile=weather]').waitFor({state:'visible'});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.locator('#edit-home').tap();await page.locator('[data-home-slot-choice="3"]').tap();
    await page.locator('[data-home-choice=lists]').tap();await page.locator('#home-tiles-save').tap();
    assert.deepEqual(await layout(),['clock','weather','rooms','lists']);
    // Invalid stored IDs cannot become markup or leave the page empty.
    await page.evaluate(()=>localStorage.setItem('echo-display-home-tiles-v1','["clock","bad","clock",null]'));
    await page.reload();assert.deepEqual(await layout(),['clock','weather','rooms','music']);
    assert.deepEqual(errors,[]);
    console.log('PASS: tile selection, swap/hide/reset, persistence, live music, touch navigation, boundaries and control/keyboard isolation, desktop and phone layout.');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

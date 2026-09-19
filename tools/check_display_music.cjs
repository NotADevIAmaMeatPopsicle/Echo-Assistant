/* Real browser, synthetic state only. Never plays audio or sends home actions. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
  fs.mkdirSync('output/playwright',{recursive:true});
  const browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1024,height:600}}),errors=[],commands=[];
    assert.equal((await (await page.request.get('http://127.0.0.1:8788/health')).json()).display_demo,true);
    for(const [action,value] of [['seek',83000],['volume',75],['shuffle',false],['repeat','off']])await page.request.post('http://127.0.0.1:8788/v1/music/control',{data:{action,value}});
    page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/*',route=>new URL(route.request().url()).hostname==='127.0.0.1'?route.continue():route.abort());
    await page.route('**/v1/music/control',route=>{commands.push(route.request().postDataJSON());return route.continue();});
    await page.addInitScript(()=>{HTMLMediaElement.prototype.play=()=>{throw new Error('Physical audio forbidden in UI check');};});
    await page.goto('http://127.0.0.1:8788/display#music');
    await page.locator('#track-cover:visible').waitFor();
    assert.equal(await page.locator('#track-title').textContent(),'Room to breathe');
    assert.equal(await page.locator('#track-elapsed').textContent(),'1:23');
    const cover=await page.locator('.album-art').boundingBox(),bottom=await page.locator('.music-library').boundingBox();
    assert.ok(cover.width>=220);assert.ok(bottom.y+bottom.height<575,JSON.stringify(bottom));
    await page.screenshot({path:'output/playwright/display-music.png',animations:'disabled'});
    await page.locator('#shuffle-track:not([disabled])').click();
    await page.waitForFunction(()=>document.getElementById('shuffle-track').getAttribute('aria-pressed')==='true');
    await page.locator('#repeat-track:not([disabled])').click();
    await page.waitForFunction(()=>document.getElementById('repeat-track').getAttribute('aria-label')==='Repeat: context');
    await page.locator('#track-seek').fill('120000');await page.locator('#track-seek').dispatchEvent('change');
    await page.waitForFunction(()=>document.getElementById('track-elapsed').textContent==='2:00');
    await page.locator('#spotify-volume:not([disabled])').fill('3');await page.locator('#spotify-volume').dispatchEvent('change');
    await page.waitForFunction(()=>document.getElementById('spotify-volume-label').textContent==='3%');
    await page.locator('#tab-local').click();assert.ok(await page.locator('#local-panel').isVisible());
    await page.locator('#tab-local').press('ArrowRight');assert.ok(await page.locator('#speakers-panel').isVisible());
    await page.locator('#tab-speakers').press('Home');assert.ok(await page.locator('#spotify-panel').isVisible());
    await page.route('**/v1/music/now-playing',route=>route.fulfill({json:{status:'unavailable',available:false}}));
    await page.route('**/v1/voice',route=>route.fulfill({json:{status:'wifi_waiting',music:{status:'disconnected'}}}));
    await page.waitForFunction(()=>document.getElementById('play-track').disabled);
    assert.ok(await page.locator('#track-cover').isHidden());assert.ok(await page.locator('#track-seek').isDisabled());
    await page.screenshot({path:'output/playwright/display-music-offline.png',animations:'disabled'});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:'output/playwright/display-music-phone.png',fullPage:true,animations:'disabled'});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    assert.ok(commands.some(c=>c.action==='seek'&&c.value===120000));assert.ok(commands.some(c=>c.action==='volume'&&c.value===3));
    assert.deepEqual(errors,[]);console.log('Music: cover, progress, controls, source tabs, offline fallback and phone layout passed. Silent synthetic data only.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

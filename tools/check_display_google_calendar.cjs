/* Synthetic account UI only. Never navigate to Google or open audio devices. */
const {previewBase}=require('./display_check.cjs');
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});
 try{
  const base=await previewBase(),page=await browser.newPage({viewport:{width:1024,height:600}});
  const errors=[],writes=[];let approved=false,role='owner';
  const state={revision:1,client_id:'123-example.apps.googleusercontent.com',redirect_uri:'https://echo.example.com/v1/calendar/google/callback',secret_saved:true,enabled:true,accounts:[]};
  page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{
    Object.defineProperty(navigator,'mediaDevices',{value:{enumerateDevices:async()=>[],addEventListener(){},getUserMedia(){throw Error('No physical microphone');}}});
    HTMLMediaElement.prototype.play=()=>{throw Error('No physical playback');};
  });
  await page.route('**/*',route=>{
    const req=route.request(),url=new URL(req.url());if(url.origin!==base)return route.abort();
    if(url.pathname==='/v1/display/session')return route.fulfill({json:{role,...(role==='display'?{receiver_id:'a'.repeat(32)}:{})}});
    if(url.pathname==='/v1/calendar/google'){
      if(req.method()==='PUT'){writes.push('configure');Object.assign(state,req.postDataJSON(),{revision:2});delete state.client_secret;}
      return route.fulfill({json:state});
    }
    if(url.pathname==='/v1/calendar/google/flows'){
      writes.push('begin');return route.fulfill({json:{id:'b'.repeat(32),url:'https://accounts.google.com/o/oauth2/v2/auth?client_id=example&state=synthetic',expires_at:Date.now()/1000+600}});
    }
    if(url.pathname.startsWith('/v1/calendar/google/flows/')){
      if(url.pathname.endsWith('/finish')){writes.push('finish');state.accounts=[{id:'c'.repeat(32),label:'Sample account',calendar_count:0}];return route.fulfill({json:{id:'c'.repeat(32),connected:true}});}
      if(req.method()==='DELETE'){writes.push('cancel');return route.fulfill({json:{cancelled:true}});}
      return route.fulfill({json:{status:approved?'approved':'waiting'}});
    }
    if(url.pathname.startsWith('/v1/calendar/google/accounts/')){
      if(req.method()==='DELETE'){writes.push('disconnect');state.accounts=[];return route.fulfill({json:{disconnected:true}});}
      writes.push('sync');state.accounts[0].calendar_count=2;return route.fulfill({json:{calendar_count:2}});
    }
    return route.continue();
  });
  await page.goto(base+'/display#settings');await page.locator('#google-load').click();
  await page.waitForFunction(()=>data.health?.display_demo);assert.equal(await page.locator('#google-client-secret').inputValue(),'');
  await page.locator('#google-begin').click();assert.equal(writes.includes('begin'),false,'Preview must not start real OAuth');
  await page.evaluate(()=>{data.health.display_demo=false;});await page.locator('#google-begin').click();
  await page.waitForFunction(()=>!document.getElementById('google-flow').hidden);
  assert.equal(new URL(await page.locator('#google-signin').getAttribute('href')).origin,'https://accounts.google.com');
  assert.equal(await page.locator('#google-finish').isVisible(),false);
  approved=true;await page.locator('#google-finish').waitFor({state:'visible',timeout:6000});
  await page.locator('#google-finish').click();await page.waitForFunction(()=>document.getElementById('google-accounts').textContent.includes('2 calendars'));
  assert.deepEqual(writes,['begin','finish','sync']);
  assert.ok(!(await page.content()).includes('refresh_token'));
  await page.locator('#google-calendar-card').scrollIntoViewIfNeeded();await page.evaluate(()=>document.getElementById('toast').hidden=true);
  fs.mkdirSync('output/playwright',{recursive:true});await page.screenshot({path:'output/playwright/display-google-calendar.png',animations:'disabled'});
  page.once('dialog',dialog=>dialog.accept());await page.locator('[data-google-disconnect]').click();await page.waitForFunction(()=>document.getElementById('google-accounts').textContent==='');
  await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  role='display';await page.reload();await page.waitForFunction(()=>data.session?.role==='display');assert.equal(await page.locator('#google-calendar-card').isVisible(),false);
  assert.deepEqual(errors,[]);console.log('Google Calendar UI: preview refusal, separate approval/finish, list refresh, secret omission, disconnect, phone layout and owner-only setup passed.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});

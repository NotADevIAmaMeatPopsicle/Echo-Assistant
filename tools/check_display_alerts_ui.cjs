/* Synthetic UI only. No playback, microphone capture, or real-device requests. */
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
  const browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const base=process.env.ECHO_PREVIEW_URL||'http://127.0.0.1:8789',page=await browser.newPage({viewport:{width:1024,height:600}});
    assert.equal((await (await page.request.get(base+'/health')).json()).display_demo,true);
    let settings={enabled:false,output:'',volume:2},items=[],commands=[];const errors=[];
    await page.addInitScript(()=>{HTMLMediaElement.prototype.play=()=>{throw Error('Audio forbidden');};Object.defineProperty(navigator,'mediaDevices',{value:{enumerateDevices:async()=>[],addEventListener(){},getUserMedia(){throw Error('Capture forbidden');}}});});
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/*',route=>{
      const request=route.request(),url=new URL(request.url());if(url.origin!==base)return route.abort();
      if(url.pathname==='/v1/display/alert-settings'){
        if(request.method()==='PUT'){settings=request.postDataJSON();commands.push(url.pathname);}
        return route.fulfill({json:{supported:true,settings,outputs:[{id:'plughw:CARD=Sample',name:'Sample speaker'}],error:null,current:null}});
      }
      if(url.pathname==='/v1/display/alerts')return route.fulfill({json:{destination:'display:'+'a'.repeat(32),items}});
      if(request.method()!=='GET'){
        if(url.pathname.startsWith('/v1/timers/')){commands.push(url.pathname);items=[];return route.fulfill({json:{ok:true}});}
        return route.abort();
      }
      return route.continue();
    });
    await page.goto(base+'/display#settings');await page.locator('#pi-alert-form').waitFor({timeout:10000}).catch(async error=>{console.log(JSON.stringify({errors,state:await page.evaluate(()=>({ready:document.readyState,data:typeof data==='undefined'?null:data.alertSettings,display:document.getElementById('page-settings').hidden,notice:document.getElementById('pi-alert-status')?.textContent}))}));throw error;});
    assert.equal(await page.locator('#pi-alert-volume').inputValue(),'2');assert.equal(await page.locator('#pi-alert-enabled').isChecked(),false);
    await page.locator('#pi-alert-output').selectOption('plughw:CARD=Sample');await page.locator('#pi-alert-enabled').check();await page.locator('#pi-alert-form button').click();await page.waitForFunction(()=>!busy);
    assert.equal(settings.output,'plughw:CARD=Sample');assert.equal(settings.volume,2);assert.equal(settings.enabled,true);
    items=[{id:'b'.repeat(32),label:'Tea is ready',finished:true,notified:false,remaining_seconds:0,audible:true,occurrence:'1'}];
    await page.locator('[data-page="timers"]').first().click();await page.locator('#pi-alert-banner:visible').waitFor();
    assert.match(await page.locator('#pi-alert-banner').textContent(),/Tea is ready/);
    const bounds=await page.locator('#pi-alert-banner').boundingBox();assert.ok(bounds.x>=0&&bounds.y>=0&&bounds.x+bounds.width<=1024&&bounds.y+bounds.height<=600);
    fs.mkdirSync('output/playwright',{recursive:true});await page.screenshot({path:'output/playwright/pi-alerts.png',animations:'disabled'});
    await page.locator('[data-alert-action="snooze"]').click();await page.waitForFunction(()=>!busy);assert.ok(commands.includes('/v1/timers/'+'b'.repeat(32)+'/snooze'));
    items=[{id:'c'.repeat(32),label:'Another timer',finished:true,notified:true,remaining_seconds:0,audible:false,occurrence:'2'}];
    await page.locator('#pi-alert-banner:visible').waitFor();await page.waitForFunction(()=>document.getElementById('pi-alert-banner').textContent.includes('Another timer'));
    await page.setViewportSize({width:390,height:844});const mobile=await page.locator('#pi-alert-banner').boundingBox();assert.ok(mobile.x>=0&&mobile.x+mobile.width<=390);
    await page.locator('[data-alert-action="dismiss"]').click();await page.waitForFunction(()=>!busy);assert.ok(commands.includes('/v1/timers/'+'c'.repeat(32)));
    assert.deepEqual(errors,[]);console.log('PASS: quiet default, Pi settings, ready banner, snooze/dismiss, 1024x600 and phone layout. No audio or devices.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});

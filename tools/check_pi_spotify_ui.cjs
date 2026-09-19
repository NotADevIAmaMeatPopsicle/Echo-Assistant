/* Simulated local receiver; cannot record, play, or contact Spotify/home devices. */
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
  const browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const base=process.env.ECHO_PREVIEW_URL||'http://127.0.0.1:8789',page=await browser.newPage({viewport:{width:1024,height:600}});
    assert.equal((await (await page.request.get(base+'/health')).json()).display_demo,true);
    const errors=[],commands=[];let settings={enabled:true,name:'Kitchen Echo',output:'plughw:CARD=Sample',volume:2},localReady=true;
    await page.addInitScript(()=>{
      window.captureOrder=[];HTMLMediaElement.prototype.play=()=>{throw Error('Physical audio forbidden');};
      Object.defineProperty(navigator,'mediaDevices',{value:{enumerateDevices:async()=>[{kind:'audioinput'}],addEventListener(){},getUserMedia(){window.captureOrder.push('mic');return Promise.reject(Error('Synthetic microphone unavailable'));}}});
    });
    page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/*',async route=>{
      const request=route.request(),url=new URL(request.url());if(url.origin!==base)return route.abort();
      if(url.pathname==='/v1/display/voice')return route.fulfill({json:{available:true}});
      if(url.pathname==='/v1/voice')return route.fulfill({json:{status:'connecting'}});
      if(url.pathname==='/v1/display/music/settings'){
        if(request.method()==='PUT')settings=request.postDataJSON();
        return route.fulfill({json:{supported:true,settings,outputs:[{id:'plughw:CARD=Sample',name:'Sample speaker'}],runtime_installed:true,status:'playing'}});
      }
      if(url.pathname==='/v1/display/music/now-playing')return route.fulfill({json:{supported:true,available:localReady,status:localReady?'playing':'unavailable',receiver_name:settings.name,output_volume:settings.volume,output_configured:true,title:'Room to breathe',artist:'Sample artist',album:'Synthetic album',position_ms:83000,duration_ms:246000,shuffle:false,repeat:'off',volume:50,capabilities:['seek','shuffle','repeat','volume'],artwork:localReady?'/v1/display/music/artwork/'+'a'.repeat(64):null}});
      if(url.pathname.endsWith('/music/control')){commands.push([url.pathname,request.postDataJSON()]);return route.fulfill({json:{status:'accepted'}});}
      if(url.pathname==='/v1/display/music/focus'){
        if(request.postDataJSON().busy)await page.evaluate(()=>window.captureOrder.push('focus'));
        return route.fulfill({json:{paused_for_voice:request.postDataJSON().busy}});
      }
      if(request.method()!=='GET')return route.abort();return route.continue();
    });
    await page.goto(base+'/display#music');await page.locator('#track-cover:visible').waitFor();
    assert.equal(await page.locator('#music-receiver').inputValue(),'display');
    assert.equal(await page.locator('#music-output-name').textContent(),'Kitchen Echo');assert.ok(await page.locator('#play-track').isEnabled());assert.match(await page.locator('#music-output-note').textContent(),/this Pi/);
    await page.locator('#play-track').click();assert.equal(commands[0][0],'/v1/display/music/control');
    await page.locator('#spotify-phone-open').click();assert.equal(await page.locator('#spotify-picker-title').textContent(),'Choose Kitchen Echo.');await page.locator('#spotify-phone-close').click();
    await page.locator('#music-receiver').selectOption('round');await page.waitForFunction(()=>document.getElementById('music-status').textContent==='Round speaker offline');assert.ok(await page.locator('#play-track').isDisabled());
    await page.locator('#music-receiver').selectOption('display');await page.waitForFunction(()=>!document.getElementById('play-track').disabled);
    fs.mkdirSync('output/playwright',{recursive:true});await page.screenshot({path:'output/playwright/pi-spotify.png',animations:'disabled'});
    await page.locator('[data-page="settings"]').first().click();await page.locator('#pi-audio-form').waitFor();await page.locator('#pi-receiver-name').fill('Desk Echo');await page.locator('#pi-audio-form button[type="submit"]').click();
    await page.waitForFunction(()=>!busy);assert.equal(settings.name,'Desk Echo');assert.equal(settings.volume,2);
    await page.locator('[data-page="assistant"]').first().click();await page.locator('#voice-start:not([disabled])').click();await page.waitForFunction(()=>window.captureOrder.includes('mic'));
    const order=await page.evaluate(()=>window.captureOrder);assert.ok(order.indexOf('focus')<order.indexOf('mic'));
    await page.locator('[data-page="music"]').first().click();localReady=false;await page.evaluate(()=>refreshVoice());await page.waitForFunction(()=>document.getElementById('play-track').disabled);
    assert.equal(commands.length,1);await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));assert.deepEqual(errors,[]);
    console.log('Pi receiver selection, output settings, independent controls, phone QR naming and pause-before-mic passed. Synthetic audio only.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});

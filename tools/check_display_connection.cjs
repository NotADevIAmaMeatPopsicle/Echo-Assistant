/* Connection failures use synthetic responses. No sound, chat, or home actions. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
  const browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1024,height:600}}),errors=[];
    const base=process.env.ECHO_PREVIEW_URL||'http://127.0.0.1:8788';
    assert.equal((await (await page.request.get(base+'/health')).json()).display_demo,true);
    let mode='speaker-offline';
    page.on('pageerror',e=>errors.push(e.message));
    await page.addInitScript(()=>{HTMLMediaElement.prototype.play=()=>{throw Error('Audio forbidden in connection check');};Object.defineProperty(navigator,'mediaDevices',{value:{enumerateDevices:async()=>[{kind:'audioinput'}],addEventListener(){},getUserMedia(){throw Error('Recording forbidden in connection check');}}});});
    await page.route('**/*',async route=>{
      const request=route.request(),url=new URL(request.url());
      if(url.origin!==base||request.method()!=='GET')return route.abort();
      if(mode==='host-offline'&&url.pathname.startsWith('/v1/'))return route.fulfill({status:503,json:{detail:'Synthetic host outage'}});
      if(mode==='pairing'&&url.pathname.startsWith('/v1/'))return route.fulfill({status:401,headers:{'X-Echo-Display-Bridge':'1'},json:{detail:'Synthetic revoked pairing'}});
      if(url.pathname==='/v1/display/voice')return route.fulfill({json:{available:mode!=='display-speech-unavailable'}});
      if(url.pathname==='/health')return route.fulfill({json:{status:'ready'}});
      if(url.pathname==='/v1/voice')return mode==='voice-unavailable'?route.fulfill({status:503,json:{detail:'Synthetic voice outage'}}):route.fulfill({json:{status:mode==='ready'?'armed':'connecting',music:{status:'paused'}}});
      return route.continue();
    });
    await page.goto(base+'/display#music');
    await page.waitForFunction(()=>document.getElementById('connection').textContent==='Display connected');
    assert.equal(await page.locator('#music-status').textContent(),'Round speaker offline');
    assert.ok(await page.locator('#play-track').isDisabled());
    assert.match(await page.locator('#music-output-note').textContent(),/optional round speaker/);
    assert.equal(await page.locator('#voice-caption').textContent(),'Ready when you are.');
    assert.equal(await page.locator('[data-orb]').first().getAttribute('data-state'),'ready');
    assert.doesNotMatch(await page.locator('#wake-word-status').textContent(),/round speaker/);
    async function refresh(){await page.waitForFunction(()=>!polling&&!voicePolling);await page.evaluate(()=>refresh());}
    mode='voice-unavailable';await refresh();
    assert.equal(await page.locator('#connection').textContent(),'Display connected');
    assert.equal(await page.locator('#music-status').textContent(),'Speaker status unavailable');
    assert.equal(await page.locator('#voice-caption').textContent(),'Ready when you are.');
    mode='display-speech-unavailable';await refresh();
    assert.match(await page.locator('#voice-detail').textContent(),/Speech service is unavailable/);
    assert.ok(await page.locator('#send-chat').isEnabled());
    mode='host-offline';await refresh();
    assert.equal(await page.locator('#connection').textContent(),'Host unreachable · retrying');
    assert.equal(await page.locator('#voice-caption').textContent(),'Reconnecting to Echo…');
    assert.ok(await page.locator('#send-chat').isDisabled());
    mode='pairing';await refresh();
    assert.equal(await page.locator('#connection').textContent(),'Pairing / sign-in needed');
    assert.match(await page.locator('#notice').textContent(),/pairing again/);
    mode='ready';await refresh();
    assert.equal(await page.locator('#connection').textContent(),'Display connected');
    assert.ok(await page.locator('#notice').isHidden());
    assert.ok(await page.locator('#send-chat').isEnabled());
    assert.ok(await page.locator('#play-track').isEnabled());
    await page.evaluate(()=>{microphoneState='none';voiceButtons();});
    assert.match(await page.locator('#voice-detail').textContent(),/Connect a microphone/);
    assert.equal(await page.locator('[data-orb]').first().getAttribute('data-state'),'ready');
    assert.deepEqual(errors,[]);
    console.log('Independent display audio, optional round speaker, speech-service, pairing, and recovery states passed. No sound or device actions.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});

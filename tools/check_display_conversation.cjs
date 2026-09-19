const {previewBase}=require('./display_check.cjs');
/* Synthetic UI check. Fake capture and model responses; never opens real audio. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
  const base=await previewBase();
  fs.mkdirSync('output/playwright',{recursive:true});
  const browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1024,height:600}}),errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/*',route=>new URL(route.request().url()).hostname==='127.0.0.1' ? route.continue() : route.abort());
    let chats=0,voices=0;
    await page.route('**/v1/chat',route=>{
      const body=route.request().postDataJSON();assert.equal(body.allow_home_actions,false);chats++;
      return route.fulfill({json:{status:'complete',text:chats===1 ? 'Start with one useful thing, then give yourself a proper break. A plan should help you, not become another job.' : 'Twenty-five minutes of focus, five minutes off. Make the first task small enough to actually finish.'}});
    });
    await page.route('**/v1/display/voice*',async route=>{
      if(route.request().method()==='GET')return route.fulfill({json:{available:true,max_seconds:8,mode:'push_to_talk'}});
      voices++;assert.equal(await page.evaluate(()=>window.stoppedTracks),1);
      assert.equal(new URL(route.request().url()).searchParams.get('reply_audio'),'false');
      assert.equal(route.request().postDataBuffer().length,3244);
      return route.fulfill({json:{status:'complete',transcript:'Add coffee to my shopping list.',text:'Coffee is on the list. Future you approves.'}});
    });
    await page.addInitScript(()=>{
      window.stoppedTracks=0;
      Object.defineProperty(navigator,'mediaDevices',{value:{enumerateDevices:async()=>[{kind:'audioinput'}],addEventListener:()=>{},getUserMedia:async()=>({getTracks:()=>[{stop:()=>window.stoppedTracks++}]})}});
      window.AudioContext=class{constructor(){this.state='running';this.audioWorklet={addModule:async()=>{}};this.destination={};}createMediaStreamSource(){return{connect:()=>{}};}createGain(){return{gain:{value:0},connect:()=>{}};}async close(){this.state='closed';}async resume(){}};
      window.AudioWorkletNode=class{constructor(){this.port={onmessage:null};window.fakeCapture=this;}connect(){}disconnect(){}};
    });
    await page.goto(base+'/display#assistant');
    await page.locator('#voice-start:not([disabled])').waitFor();
    await page.screenshot({path:'output/playwright/display-echo-empty.png',animations:'disabled'});
    const presence=await page.locator('.echo-presence').boundingBox(),settings=await page.locator('.echo-controls').boundingBox(),chat=await page.locator('.echo-conversation').boundingBox(),composer=await page.locator('.chat-composer').boundingBox();
    assert.ok(settings.y>=presence.y+presence.height);assert.ok(chat.x>presence.x+presence.width);assert.ok(composer.y+composer.height<590);
    await page.locator('#chat-text').fill('Help me plan a calmer afternoon.');await page.locator('#send-chat').click();
    await page.getByText('A plan should help you',{exact:false}).waitFor();
    await page.locator('#chat-text').fill('How long should I focus for?');await page.locator('#send-chat').click();
    await page.getByText('Twenty-five minutes of focus',{exact:false}).waitFor();
    assert.equal(await page.locator('.chat-message').count(),4);
    await page.screenshot({path:'output/playwright/display-echo-conversation.png',animations:'disabled'});
    await page.locator('#voice-speak').uncheck();await page.locator('#voice-start').click();
    await page.waitForFunction(()=>document.getElementById('assistant-phase').textContent==='I’m listening.');
    await page.evaluate(()=>window.fakeCapture.port.onmessage({data:{type:'pcm',data:new Int16Array(1600).buffer}}));
    await page.locator('#voice-send').click();await page.locator('.chat-message').getByText('Coffee is on the list. Future you approves.',{exact:true}).waitFor();
    assert.equal(voices,1);assert.equal(await page.locator('.chat-message').count(),6);
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.locator('.echo-conversation').scrollIntoViewIfNeeded();
    await page.screenshot({path:'output/playwright/display-echo-phone.png',animations:'disabled'});
    assert.deepEqual(errors,[]);
    console.log('Passed: presence/settings/chat layout, retained conversation, simulated mic-to-chat, capture closes before upload, phone width; no real microphone, speech, or home actions.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

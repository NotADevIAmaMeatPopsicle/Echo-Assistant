const {previewBase}=require('./display_check.cjs');
/* Browser call lifecycle with synthetic microphone/worklet/stream, never hardware. */
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
  const browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const base=await previewBase(),page=await browser.newPage({viewport:{width:1024,height:600}});
    assert.equal((await (await page.request.get(base+'/health')).json()).display_demo,true);
    const errors=[],uploads=[],mutations=[];let call=null;
    page.on('pageerror',e=>errors.push(e.message));
    await page.addInitScript(()=>{
      window.micOpens=0;window.micStops=0;window.icNodes=[];window.deferMic=false;window.resolveMic=null;
      Object.defineProperty(navigator,'mediaDevices',{value:{enumerateDevices:async()=>[{kind:'audioinput'}],addEventListener(){},getUserMedia:()=>{
        window.micOpens++;const stream={getTracks:()=>[{stop(){window.micStops++;},addEventListener(){}}]};
        return window.deferMic?new Promise(resolve=>window.resolveMic=()=>resolve(stream)):Promise.resolve(stream);
      }}});
      window.AudioContext=class{constructor(){this.state='suspended';this.destination={};this.audioWorklet={addModule:async()=>{}};}async resume(){this.state='running';}createGain(){return{gain:{value:0},connect(){},disconnect(){}};}createMediaStreamSource(){return{connect(){},disconnect(){}};}};
      window.AudioWorkletNode=class{constructor(){this.posts=[];this.port={onmessage:null,postMessage:m=>this.posts.push(m)};window.icNodes.push(this);}connect(){}disconnect(){}};
      HTMLMediaElement.prototype.play=()=>{throw Error('Physical audio forbidden');};
      const fetch=window.fetch.bind(window);window.fetch=(url,options={})=>{
        if(String(url).includes('/v1/intercom/calls/')&&String(url).includes('/audio?')&&(!options.method||options.method==='GET')){
          return Promise.resolve(new Response(new ReadableStream({start(controller){window.remoteAudio=controller;options.signal?.addEventListener('abort',()=>controller.error(new DOMException('Aborted','AbortError')));}}),{headers:{'Content-Type':'application/x-echo-pcm'}}));
        }
        return fetch(url,options);
      };
    });
    await page.route('**/*',route=>{
      const request=route.request(),url=new URL(request.url());if(url.origin!==base)return route.abort();
      if(url.pathname==='/v1/display/session')return route.fulfill({json:{role:'display',receiver_id:'a'.repeat(32)}});
      if(url.pathname==='/v1/intercom/heartbeat'){
        const enabled=request.postDataJSON().enabled;
        return route.fulfill({json:{enabled:true,ready:enabled&&(!call||call.status==='ended'),status:enabled?'ready':'calls_off',revision:1,call,rooms:[{id:'b'.repeat(32),room:'Kitchen',ready:true,status:'ready'}]}});
      }
      if(url.pathname==='/v1/intercom/calls'){
        mutations.push('call');call={id:request.postDataJSON().id,direction:'outgoing',peer:'b'.repeat(32),room:'Kitchen',status:'ringing',seconds:0,muted:true,peer_muted:true};return route.fulfill({json:call});
      }
      if(url.pathname.startsWith('/v1/intercom/calls/')){
        const action=url.pathname.split('/').pop();mutations.push(action);
        if(action==='audio'){uploads.push(request.postDataBuffer());return route.fulfill({json:{accepted:Number(url.searchParams.get('sequence'))}});}
        if(action==='accept')call.status='active';if(action==='mute')call.muted=request.postDataJSON().muted;if(action==='end'){call.status='ended';call.reason='hangup';}
        return route.fulfill({json:call});
      }
      return route.continue();
    });
    await page.goto(base+'/display#audio');await page.locator('#room-tab-intercom').click();
    await page.waitForFunction(()=>!!data.session?.receiver_id);await page.evaluate(()=>icPoll());
    await page.locator('#intercom-enable').click();assert.equal(await page.evaluate(()=>window.micOpens),0);
    await page.locator('[data-call-room]:not([disabled])').click();
    await page.waitForFunction(()=>icCall?.status==='ringing');assert.equal(uploads.length,0);assert.equal(await page.evaluate(()=>window.micOpens),1);
    call.status='active';await page.evaluate(()=>icPoll());await page.waitForFunction(()=>window.icNodes.length===1&&!!window.remoteAudio);
    await page.evaluate(()=>window.icNodes[0].port.onmessage({data:{type:'pcm',data:new Int16Array(1600).fill(4).buffer}}));
    await page.waitForFunction(()=>!icUploading);assert.equal(uploads.length,1);assert.equal(uploads[0].length,3200);
    await page.evaluate(()=>{const raw=new Uint8Array(3208),header=new DataView(raw.buffer);header.setUint32(0,0,true);header.setUint32(4,3200,true);window.remoteAudio.enqueue(raw.slice(0,5));window.remoteAudio.enqueue(raw.slice(5));});
    await page.waitForFunction(()=>window.icNodes[0].posts.some(p=>p.type==='pcm'));
    fs.mkdirSync('output/playwright',{recursive:true});await page.screenshot({path:'output/playwright/display-intercom.png',animations:'disabled'});
    await page.locator('#intercom-mute').click();assert.equal(await page.evaluate(()=>window.micStops),1);assert.equal(call.muted,true);
    await page.locator('#intercom-mute').click();assert.equal(await page.evaluate(()=>window.micOpens),2);assert.equal(call.muted,false);
    await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.locator('#intercom-end').click();assert.equal(await page.evaluate(()=>window.micStops),2);
    call={id:'e'.repeat(32),direction:'incoming',peer:'b'.repeat(32),room:'Kitchen',status:'ringing',seconds:0,muted:true,peer_muted:true};
    await page.evaluate(()=>icPoll());await page.locator('#intercom-banner-answer').waitFor();assert.equal(await page.evaluate(()=>window.micOpens),2);
    await page.evaluate(()=>window.deferMic=true);await page.locator('#intercom-banner-answer').click();
    await page.waitForFunction(()=>!!window.resolveMic);await page.locator('#intercom-banner-decline').click();await page.evaluate(()=>window.resolveMic());
    await page.waitForFunction(()=>window.micStops===3);
    assert.equal(mutations.filter(v=>v==='accept').length,0);assert.equal(await page.evaluate(()=>icMic===null),true);assert.deepEqual(errors,[]);
    console.log('Intercom browser: explicit call/answer, live PCM send/receive, mute/unmute, hang-up, phone layout and delayed permission cancellation passed. No physical audio.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});

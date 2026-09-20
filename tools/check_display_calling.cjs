/* Synthetic call lifecycle and media objects. No audio devices or provider network. */
const {previewBase}=require('./display_check.cjs');
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});
 try{
  const base=await previewBase(),page=await browser.newPage({viewport:{width:1024,height:600}}),errors=[],actions=[];
  let failPulse=false;
  page.on('pageerror',e=>errors.push(e.message));
  const fake=`window.fakeTracks=[];window.fakeRooms=[];window.deferCapture=false;window.resolveCapture=null;
  function fakeTrack(kind){const t={kind,stopped:false,volume:null,elements:[],stop(){this.stopped=true;},setVolume(v){this.volume=v;},attach(){if(kind==='audio'&&this.remote&&this.volume!==.02)throw Error('Remote volume must be quiet before attach');const el=document.createElement(kind==='audio'?'audio':'video');this.elements.push(el);return el;},detach(){const els=this.elements;this.elements=[];return els;}};window.fakeTracks.push(t);return t;}
  window.fakeTrack=fakeTrack;
  window.LivekitClient={RoomEvent:Object.fromEntries(['TrackSubscribed','TrackUnsubscribed','Disconnected','Reconnecting','Reconnected','ParticipantConnected','ParticipantDisconnected','AudioPlaybackStatusChanged'].map(x=>[x,x])),Room:class{constructor(){this.events={};this.canPlaybackAudio=true;this.localParticipant={publishTrack:async()=>{},unpublishTrack:async()=>{}};window.fakeRooms.push(this);}on(n,fn){this.events[n]=fn;return this;}async connect(){this.connected=true;}async disconnect(){this.connected=false;}async startAudio(){}},createLocalAudioTrack:async()=>{const t=fakeTrack('audio');if(window.deferCapture)return new Promise(r=>window.resolveCapture=()=>r(t));return t;},createLocalVideoTrack:async()=>fakeTrack('video')};`;
  await page.addInitScript(()=>{
    Object.defineProperty(navigator,'mediaDevices',{value:{enumerateDevices:async()=>[],addEventListener(){},getUserMedia(){throw Error('Physical microphone forbidden');}}});
    HTMLMediaElement.prototype.play=()=>{throw Error('Physical playback forbidden');};
  });
  await page.route('**/*',route=>{
    const req=route.request(),url=new URL(req.url());if(url.origin!==base)return route.abort();
    if(url.pathname.includes('/vendor/livekit-'))return route.fulfill({contentType:'application/javascript',body:fake});
    if(url.pathname==='/v1/calling')return route.fulfill({json:{enabled:true,allowed:true,provider:'LiveKit'}});
    if(url.pathname==='/v1/calling/settings')return route.fulfill({json:{revision:0,enabled:true,url:'wss://calls.example.com',credentials_saved:true,allowed_displays:[],displays:[]}});
    if(url.pathname.startsWith('/v1/calling/')){
      const action=url.pathname.split('/').pop();actions.push(action);
      if(action==='pulse')return route.fulfill(failPulse?{status:403,json:{detail:'Access removed'}}:{json:{active:true,joined:true}});
      if(action==='end')return route.fulfill({json:{ended:true}});
      return route.fulfill({json:{id:'a'.repeat(32),url:'wss://calls.example.com',token:'synthetic',expires_at:Date.now()/1000+900,invite_expires_at:Date.now()/1000+120,...(action==='start'?{code:'b'.repeat(32)}:{})}});
    }
    return route.continue();
  });
  await page.goto(base+'/display#audio');assert.deepEqual(errors,[]);await page.locator('#room-tab-calling').click({timeout:5000});
  await page.waitForFunction(()=>data.calling?.enabled&&data.health?.display_demo);
  await page.locator('#calling-start').click();assert.equal(actions.length,0,'Demo must not call a provider');
  await page.evaluate(()=>{data.health.display_demo=false;});
  await page.locator('#calling-start').click();await page.waitForFunction(()=>window.fakeTracks.length===1&&!document.getElementById('calling-mute').disabled);
  assert.equal((await page.locator('#calling-code').textContent()).replaceAll(' ',''),'b'.repeat(32));
  assert.equal(await page.evaluate(()=>displayCaptureBusy),true);
  await page.evaluate(()=>{const t=fakeTrack('audio');t.remote=true;fakeRooms.at(-1).events.TrackSubscribed(t);});
  assert.equal(await page.evaluate(()=>fakeTracks.at(-1).volume),.02);
  await page.evaluate(()=>{document.getElementById('toast').hidden=true;});
  fs.mkdirSync('output/playwright',{recursive:true});await page.screenshot({path:'output/playwright/display-calling.png',animations:'disabled'});
  await page.locator('#calling-camera').click();await page.waitForFunction(()=>fakeTracks.some(t=>t.kind==='video'));
  await page.locator('#calling-mute').click();assert.equal(await page.evaluate(()=>fakeTracks[0].stopped),true);
  await page.locator('#calling-mute').click();await page.waitForFunction(()=>fakeTracks.length===4);
  await page.locator('#calling-end').click();await page.waitForFunction(()=>!externalCallBusy());
  assert.equal(await page.evaluate(()=>fakeTracks.filter(t=>!t.remote).every(t=>t.stopped)),true);
  assert.equal(await page.locator('#calling-code').textContent(),'');
  await page.evaluate(()=>{data.health.display_demo=false;window.deferCapture=true;});
  await page.locator('#calling-start').click();await page.waitForFunction(()=>!!window.resolveCapture);
  await page.locator('#calling-end').click();await page.evaluate(()=>resolveCapture());await page.waitForFunction(()=>fakeTracks.at(-1).stopped);
  assert.equal(await page.evaluate(()=>externalCallBusy()),false,'Delayed permission cannot resurrect a call');
  await page.evaluate(()=>{data.health.display_demo=false;window.deferCapture=false;});
  await page.locator('#calling-invite').fill('b'.repeat(32));await page.locator('#calling-join').click();await page.waitForFunction(()=>externalCallBusy()&&!document.getElementById('calling-mute').disabled);
  failPulse=true;await page.waitForFunction(()=>!externalCallBusy(),null,{timeout:10000});
  assert.equal(await page.evaluate(()=>fakeTracks.filter(t=>!t.remote).every(t=>t.stopped)),true);
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Phone must not overflow');
  await page.evaluate(()=>page('settings'));await page.locator('#calling-configure').click();
  assert.equal(await page.locator('#calling-key').inputValue(),'');assert.equal(await page.locator('#calling-secret').inputValue(),'');
  assert.deepEqual(errors,[]);console.log('Calling: demo refusal, quiet audio, camera/mute, cancellation, invitation, access loss, settings redaction and phone layout passed.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

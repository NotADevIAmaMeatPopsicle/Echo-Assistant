const {previewBase}=require('./display_check.cjs');
/* Synthetic native listener. No microphone, speaker, or home actions. */
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
  const browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const base=await previewBase(),page=await browser.newPage({viewport:{width:1024,height:600}});
    assert.equal((await (await page.request.get(base+'/health')).json()).display_demo,true);
    let state={supported:true,runtime_installed:true,phase:'armed',error:null,result:null,inputs:[{id:'mic',name:'Sample microphone'}],outputs:[{id:'speaker',name:'Sample speaker'}],settings:{enabled:true,muted:false,input:'mic',output:'speaker',volume:2,echo_cancelled_input:false,allow_home:false}};
    const errors=[],commands=[],focus=[];let offline=false;
    await page.addInitScript(()=>{HTMLMediaElement.prototype.play=()=>{throw Error('No playback');};Object.defineProperty(navigator,'mediaDevices',{value:{enumerateDevices:async()=>[],addEventListener(){},getUserMedia(){throw Error('No browser microphone');}}});});
    page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/*',route=>{
      const request=route.request(),url=new URL(request.url());if(url.origin!==base)return route.abort();
      if(url.pathname==='/v1/display/voice')return route.fulfill({json:{available:true}});
      if(url.pathname==='/v1/display/local-voice'){
        if(offline)return route.fulfill({status:503,json:{detail:'Synthetic adapter offline'}});
        if(request.method()==='POST'){const action=request.postDataJSON().action;commands.push(action);if(action==='talk')state.phase='listening';if(action==='send')state.phase='thinking';if(action==='stop')state.phase='armed';if(action==='mute'){state.settings.muted=true;state.phase='muted';}if(action==='unmute'){state.settings.muted=false;state.phase='armed';}}
        if(request.method()==='PUT')state.settings=request.postDataJSON();
        return route.fulfill({json:state});
      }
      if(url.pathname==='/v1/display/music/settings')return route.fulfill({json:{supported:true,settings:{enabled:false,name:'Sample Echo',output:'speaker',volume:2},outputs:[],status:'disabled',runtime_installed:true}});
      if(url.pathname==='/v1/display/music/focus'){focus.push(request.postDataJSON().busy);return route.fulfill({json:{paused_for_voice:false}});}
      if(request.method()!=='GET')return route.abort();return route.continue();
    });
    await page.goto(base+'/display#assistant');await page.waitForFunction(()=>document.getElementById('assistant-detail').textContent.includes('Okay Echo'));
    await page.locator('#voice-start').click();await page.waitForFunction(()=>document.getElementById('assistant-phase').textContent==='I’m listening.');assert.equal(commands.at(-1),'talk');assert.ok(await page.locator('#chat-text').isDisabled());
    fs.mkdirSync('output/playwright',{recursive:true});await page.screenshot({path:'output/playwright/pi-listening.png',animations:'disabled'});
    await page.locator('#voice-send').click();await page.waitForFunction(()=>document.getElementById('assistant-phase').textContent==='On it.');
    state.phase='speaking';state.result={id:'a'.repeat(32),transcript:'Set a timer for tea.',text:'Your timer is set for five minutes.',status:'complete'};
    state.diagnostics={frame_age_seconds:.1,level_dbfs:-64,recent_peak_dbfs:-55,recent_rms_dbfs:-63,events:[{stage:'wake_detected',age_seconds:12},{stage:'no_speech',age_seconds:3}]};
    await page.waitForFunction(()=>document.getElementById('assistant-phase').textContent==='Here’s what I found.');await page.getByText('Your timer is set for five minutes.',{exact:true}).waitFor();
    await page.locator('#voice-cancel').click();assert.equal(commands.at(-1),'stop');
    await page.waitForFunction(()=>document.getElementById('pi-voice-events').textContent.includes('No usable speech'));
    assert.match(await page.locator('#pi-input-level').textContent(),/quiet/);
    await page.locator('#pi-voice-mute').click();await page.waitForFunction(()=>document.getElementById('assistant-phase').textContent==='A little quiet.');assert.ok(await page.locator('#voice-start').isDisabled());
    offline=true;await page.waitForFunction(()=>document.getElementById('assistant-phase').textContent==='Reconnecting to this Pi…');assert.ok(await page.locator('#voice-start').isDisabled());
    assert.ok(!focus.some(Boolean),'Native presence must not create a browser audio lease that cancels itself');assert.deepEqual(errors,[]);
    console.log('PASS: native talk/send/stop, live states, shared conversation, mute, stale-adapter guard; no browser audio or home actions.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});

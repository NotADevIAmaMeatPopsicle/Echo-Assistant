/* Silent video seams. Requires the synthetic preview; provider and native writes are all fake. */
const {previewBase}=require('./display_check.cjs');
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..'),assets=path.join(root,'web','display');
const eventually=async check=>{for(let n=0;n<80;n++){if(await check())return;await new Promise(resolve=>setTimeout(resolve,50));}throw Error('Synthetic condition did not finish');};
(async()=>{
  const base=await previewBase(),browser=await chromium.launch({channel:'chrome',headless:true}),release=[];
  try{
    const page=await browser.newPage({viewport:{width:1024,height:600},hasTouch:true}),errors=[],writes=[],external=[];
    const video='Synthetic_1',display='a'.repeat(32);let mode='owner',preview=true,revision=0,phase='idle',delayConfig=false,lateConfig=null,delayStart=false,lateStart=null;
    const session=()=>({role:mode==='owner'?'owner':'display',receiver_id:display,profile_revision:mode==='owner'?0:1,profile:{mode:mode==='personal'?'guest':mode==='owner'?'household':mode,personal:mode==='personal',name:'Synthetic display',conversation:true},...(mode==='personal'?{member:{id:'b'.repeat(32),expires_at:Date.now()/1000+900}}:{})});
    const view=()=>({provider:'youtube',revision,profile_revision:session().profile_revision,available:!['guest','personal'].includes(mode),...(!['guest','personal'].includes(mode)?{video_id:video,watch_url:'https://www.youtube.com/watch?v='+video,reason:mode==='owner'?'owner_preview':'allowed'}:{reason:mode+'_not_allowed'})});
    const config=()=>({revision,enabled:true,video_id:video,allowed_display_ids:[display]});
    const output=()=>({available:true,phase,error:''});
    page.on('pageerror',error=>errors.push(error.message));
    await page.addInitScript(()=>{Object.defineProperty(navigator,'mediaDevices',{value:{enumerateDevices:async()=>[],addEventListener(){},getUserMedia(){throw Error('No microphone in video check');}}});HTMLMediaElement.prototype.play=()=>{throw Error('No media playback in video check');};window.open=()=>{throw Error('No uncontrolled provider window');};});
    await page.route('**/*',async route=>{
      const req=route.request(),url=new URL(req.url());if(url.origin!==base){external.push(url.href);return route.abort();}
      if(/^\/assets\/display\/video-provider\.(js|css)$/.test(url.pathname))return route.fulfill({contentType:url.pathname.endsWith('js')?'text/javascript':'text/css',body:fs.readFileSync(path.join(assets,path.basename(url.pathname)),'utf8')});
      if(url.pathname==='/v1/display/session')return route.fulfill({json:session()});
      if(url.pathname==='/health'){const result=await route.fetch();return route.fulfill({json:{...await result.json(),display_demo:preview}});}
      if(url.pathname==='/v1/display/video')return route.fulfill({json:view()});
      if(url.pathname==='/v1/display/video/output'){
        if(req.method()==='POST'){const body=req.postDataJSON();writes.push(body);if(body.action==='start'){assert.equal(body.revision,revision);if(delayStart){lateStart=()=>route.fulfill({json:{available:true,phase:'active',error:''}});release.push(()=>lateStart?.());return;}phase='active';}else{assert.deepEqual(body,{action:'stop'});phase='idle';}}
        return route.fulfill({json:output()});
      }
      if(url.pathname==='/v1/display/video/settings'){
        if(req.method()==='PUT'){const body=req.postDataJSON();writes.push(body);assert.equal(body.revision,revision);assert.equal(body.video_id,video);assert.deepEqual(body.allowed_display_ids,[display]);revision++;return route.fulfill({json:config()});}
        if(delayConfig){const body=config();lateConfig=()=>route.fulfill({json:body});release.push(()=>lateConfig?.());return;}
        return route.fulfill({json:config()});
      }
      if(url.pathname==='/v1/displays')return route.fulfill({json:{items:[{id:display,name:'Kitchen display',profile:{mode:'household'}},{id:'c'.repeat(32),name:'Guest display',profile:{mode:'guest'}}]}});
      if(req.method()!=='GET'&&req.method()!=='HEAD'){assert.ok(!url.pathname.startsWith('/v1/display/video'),'Unexpected native video write');return route.fulfill({json:{status:'synthetic'}});}
      return route.continue();
    });
    await page.goto(base+'/display#music');
    assert.equal(await page.locator('script[src="/assets/display/video-provider.js"]').count(),0,'Main page no longer registers the video extension');
    assert.equal(await page.locator('#video-provider-card').count(),0);
    // Exercise the retained prototype in this synthetic harness only.
    await page.addStyleTag({url:base+'/assets/display/video-provider.css'});
    await page.addScriptTag({url:base+'/assets/display/video-provider.js'});
    await page.locator('#video-provider-card').waitFor({state:'visible'});
    assert.ok(await page.locator('#video-provider-start').isDisabled());assert.equal(writes.length,0);
    preview=false;await page.evaluate(()=>{data.health.display_demo=false;return EchoVideo.refresh();});
    await page.locator('#video-provider-start:not(:disabled)').waitFor();
    assert.equal(await page.locator('iframe[src*="youtube"]').count(),0);assert.equal(external.filter(x=>/youtube|ytimg|googlevideo/.test(x)).length,0);
    await page.screenshot({path:ensureOutput('display-video.png'),animations:'disabled'});
    await page.locator('#video-provider-share').tap();await page.locator('#video-provider-phone[open]').waitFor();
    assert.equal(await page.locator('#video-provider-url').inputValue(),'https://www.youtube.com/watch?v='+video);
    assert.equal(await page.locator('#video-provider-phone a').count(),0);await page.locator('#video-provider-close').tap();assert.equal(writes.length,0);
    await page.locator('#video-provider-start').tap();await eventually(()=>writes.length===1);assert.deepEqual(writes[0],{action:'start',revision:0});
    await page.locator('#video-provider-stop:not(:disabled)').waitFor();
    await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});document.dispatchEvent(new Event('visibilitychange'));});
    await page.waitForTimeout(2200);assert.equal(writes.length,1,'Hidden main kiosk must not stop or heartbeat');
    await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,get:()=>false});document.dispatchEvent(new Event('visibilitychange'));});
    await page.locator('#video-provider-stop').tap();await eventually(()=>writes.length===2);assert.deepEqual(writes[1],{action:'stop'});
    await page.setViewportSize({width:390,height:844});await page.locator('#video-provider-card').scrollIntoViewIfNeeded();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    assert.equal(await page.locator('#video-provider-card').evaluate(el=>el.scrollWidth<=el.clientWidth+1),true);
    await page.screenshot({path:ensureOutput('display-video-phone.png'),animations:'disabled'});
    await page.evaluate(()=>EchoSettings.open('system','video-provider-settings'));await page.locator('#video-provider-configure').tap();await page.locator('#video-provider-form').waitFor({state:'visible'});
    assert.equal(await page.locator('#video-provider-displays input').count(),1);assert.match(await page.locator('#video-provider-displays').innerText(),/Kitchen display/);
    await page.locator('#video-provider-save').tap();await page.locator('#video-provider-settings-status').getByText('Saved.',{exact:false}).waitFor();assert.equal(writes.length,3);assert.equal(writes[2].enabled,true);
    // A delayed command from the prior configuration cannot restore old state.
    await page.evaluate(()=>page('music'));delayStart=true;await page.locator('#video-provider-start:not(:disabled)').waitFor();await page.locator('#video-provider-start').tap();await eventually(()=>!!lateStart);
    revision++;await page.evaluate(()=>EchoVideo.refresh());await lateStart();lateStart=null;delayStart=false;await page.waitForTimeout(100);
    assert.match(await page.locator('#video-provider-status').innerText(),/Ready when/);
    // Account changes discard pending owner settings, including the private ID.
    await page.evaluate(()=>EchoSettings.open('system','video-provider-settings'));delayConfig=true;await page.locator('#video-provider-configure').tap();await eventually(()=>!!lateConfig);
    mode='guest';await page.evaluate(value=>{data.session=value;EchoVideo.reset();extensions.forEach(fn=>fn());},session());await lateConfig();lateConfig=null;delayConfig=false;
    assert.ok(await page.locator('#video-provider-settings').isHidden());assert.ok(await page.locator('#video-provider-card').isHidden());assert.equal(await page.locator('#video-provider-id').inputValue(),'');
    mode='personal';await page.evaluate(value=>{data.session=value;extensions.forEach(fn=>fn());},session());assert.ok(await page.locator('#video-provider-card').isHidden());
    mode='household';await page.evaluate(value=>{data.session=value;page('music');return EchoVideo.refresh();},session());await page.locator('#video-provider-card').waitFor({state:'visible'});assert.ok(await page.locator('#video-provider-settings').isHidden());
    assert.deepEqual(errors,[]);await page.close();

    async function playerPage({invalid=false,denied=false,held=false}={}){
      const p=await browser.newPage({viewport:{width:1024,height:600}}),calls=[],provider=[],pageErrors=[];let active=!denied,late=null,hold=held;
      p.on('pageerror',error=>pageErrors.push(error.message));
      await p.route('**/*',async route=>{
        const req=route.request(),url=new URL(req.url());
        if(url.origin===base&&url.pathname==='/display/video-player')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(assets,'video-player.html'),'utf8')});
        if(url.origin===base&&/^\/assets\/display\/video-player\.(js|css)$/.test(url.pathname))return route.fulfill({contentType:url.pathname.endsWith('js')?'text/javascript':'text/css',body:fs.readFileSync(path.join(assets,path.basename(url.pathname)),'utf8')});
        if(url.origin===base&&url.pathname==='/v1/display/video/player'){
          const body=req.postDataJSON();calls.push(body);assert.deepEqual(Object.keys(body).sort(),['action','lease']);assert.equal(body.lease,'d'.repeat(32));
          if(body.action==='stop')return route.fulfill({json:{active:false}});
          assert.equal(body.action,'pulse');if(hold){hold=false;late=()=>route.fulfill({json:{active:true,video_id:video,watch_url:'https://www.youtube.com/watch?v='+video}});release.push(()=>late?.());return;}
          return route.fulfill({status:active?200:409,json:active?{active:true,video_id:video,watch_url:'https://www.youtube.com/watch?v='+video}:{detail:'Synthetic lease revoked'}});
        }
        if(url.origin==='https://www.youtube.com'&&url.pathname==='/iframe_api'){
          provider.push(url.href);return route.fulfill({contentType:'text/javascript',body:'window.__syntheticYT={muted:0,destroyed:0};window.YT={Player:class {constructor(frame,options){this.frame=frame;window.__syntheticYT.events=options.events;setTimeout(()=>options.events.onReady({target:this}),0);}mute(){window.__syntheticYT.muted++;}destroy(){window.__syntheticYT.destroyed++;this.frame.remove();}}};window.onYouTubeIframeAPIReady();'});
        }
        if(url.origin==='https://www.youtube-nocookie.com'&&url.pathname==='/embed/'+video){provider.push(url.href);assert.equal(url.searchParams.get('autoplay'),'0');assert.equal(url.searchParams.get('mute'),'1');assert.equal(url.searchParams.get('controls'),'1');assert.equal(url.searchParams.get('origin'),base);assert.ok(!url.href.includes('d'.repeat(32)));return route.fulfill({contentType:'text/html',body:'<!doctype html><meta charset="utf-8"><body style="margin:0;background:#101722;color:#dee5f4;font:18px system-ui;display:flex;align-items:center;justify-content:center;height:100vh"><div style="text-align:center"><p style="font-size:36px;margin:0 0 12px">&#9655;</p><p style="margin:8px">Synthetic provider player</p><small>No media or network playback</small></div></body>'});}
        if(url.origin===base&&url.pathname==='/assets/icon.svg')return route.continue();
        throw Error('Unexpected player resource '+url.href);
      });
      await p.goto(base+'/display/video-player#'+(invalid?'invalid':'d'.repeat(32)));
      return {p,calls,provider,pageErrors,revoke:()=>{active=false;},held:()=>late,release:async()=>{await late();late=null;}};
    }
    const held=await playerPage({held:true});await eventually(()=>!!held.held());assert.equal(held.provider.length,0);assert.equal(await held.p.locator('iframe').count(),0);
    await held.release();await held.p.getByText('Ready · muted.',{exact:false}).waitFor();assert.equal(held.provider.length,2);assert.equal(await held.p.evaluate(()=>__syntheticYT.muted),1);assert.equal(new URL(held.p.url()).hash,'');
    await held.p.screenshot({path:ensureOutput('display-video-player.png'),animations:'disabled'});
    await held.p.setViewportSize({width:390,height:844});assert.equal(await held.p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);assert.ok((await held.p.locator('#video-player-frame').boundingBox()).height>=200);
    await held.p.screenshot({path:ensureOutput('display-video-player-phone.png'),animations:'disabled'});
    held.revoke();await held.p.getByText('Video stopped because',{exact:false}).waitFor();assert.equal(await held.p.locator('iframe').count(),0);assert.ok(await held.p.locator('#video-player-handoff').isHidden());const count=held.calls.length;await held.p.waitForTimeout(2200);assert.equal(held.calls.length,count);assert.deepEqual(held.pageErrors,[]);await held.p.close();
    for(const code of [5,100,101,150,153]){const sample=await playerPage();await sample.p.getByText('Ready · muted.',{exact:false}).waitFor();await sample.p.evaluate(value=>__syntheticYT.events.onError({data:value}),code);await sample.p.getByText('(error '+code+').',{exact:false}).waitFor();assert.equal(await sample.p.locator('iframe').count(),0);assert.ok(await sample.p.locator('#video-player-handoff').isVisible());assert.deepEqual(sample.pageErrors,[]);await sample.p.close();}
    const stopping=await playerPage();await stopping.p.getByText('Ready · muted.',{exact:false}).waitFor();await stopping.p.locator('#video-player-stop').click();await eventually(()=>stopping.calls.some(call=>call.action==='stop'));assert.equal(await stopping.p.locator('iframe').count(),0);await stopping.p.close();
    const closed=await playerPage({held:true});await eventually(()=>!!closed.held());await closed.p.locator('#video-player-stop').click();await closed.release();await closed.p.waitForTimeout(100);assert.equal(closed.provider.length,0,'Late pulse cannot reload a stopped player');assert.equal(await closed.p.locator('iframe').count(),0);assert.deepEqual(closed.pageErrors,[]);await closed.p.close();
    for(const options of [{invalid:true},{denied:true}]){const denied=await playerPage(options);await denied.p.getByText(options.invalid?'No active video permission.':'Video stopped because',{exact:false}).waitFor();assert.equal(denied.provider.length,0);assert.equal(await denied.p.locator('iframe').count(),0);assert.deepEqual(denied.pageErrors,[]);await denied.p.close();}
    console.log('PASS: video preview guard, explicit native start/stop, hidden main kiosk independence, local phone handoff, owner-only settings, stale/config/profile responses discarded, first-pulse provider gate, muted/autoplay-off official embed, lease teardown, truthful errors 5/100/101/150/153, desktop/phone layout. Every write/provider response synthetic; no audio.');
  }finally{for(const done of release)try{await done();}catch{}await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
function ensureOutput(name){fs.mkdirSync(path.join(root,'output','playwright'),{recursive:true});return path.join(root,'output','playwright',name);}

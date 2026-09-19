const {previewBase}=require('./display_check.cjs');
/* Synthetic preview and simulated Web Audio only. Never opens an audio device. */
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
  const base=await previewBase();
  const browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    fs.mkdirSync('output/playwright',{recursive:true});
    const owner=await browser.newPage({viewport:{width:1024,height:600}}),errors=[],requests=[];
    assert.equal((await (await owner.request.get(base+'/health')).json()).display_demo,true);
    for(const entry of (await (await owner.request.get(base+'/v1/audio/messages')).json()).items)await owner.request.delete(base+'/v1/audio/messages/'+entry.id);
    owner.on('pageerror',e=>errors.push(e.message));
    await owner.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
    await owner.addInitScript(()=>{window.AudioContext=class{constructor(){throw Error('Owner must not open audio');}};HTMLMediaElement.prototype.play=()=>{throw Error('Audio forbidden');};});
    await owner.goto(base+'/display#settings');
    await owner.locator('.audio-room-setting').first().waitFor();
    await owner.locator('.audio-room-setting').first().locator('[data-audio-room]').fill('Living room');
    await owner.locator('#audio-room-form button').click();
    await owner.waitForFunction(()=>document.getElementById('toast').textContent==='Room assignments saved.');
    await owner.locator('#audio-room-form').locator('..').getByText('Open room audio ↗',{exact:true}).click();
    await owner.locator('#announcement-text').fill('Dinner is ready. Meet me in the kitchen.');
    for(const checkbox of await owner.locator('#announcement-targets input').all())await checkbox.check();
    let loseReply=true;
    await owner.route('**/v1/audio/messages',async route=>{
      if(route.request().method()!=='POST')return route.continue();
      requests.push(route.request().postDataJSON());
      if(loseReply){loseReply=false;await route.fetch();return route.abort();}
      return route.continue();
    });
    await owner.locator('#announcement-send').click();
    await owner.getByRole('button',{name:'Retry same message',exact:true}).waitFor();
    await owner.locator('#announcement-send').click();
    await owner.waitForFunction(()=>document.getElementById('announcement-send').textContent==='Sent');
    assert.equal(requests.length,2);assert.deepEqual(requests[0],requests[1]);
    assert.equal((await (await owner.request.get(base+'/v1/audio/messages')).json()).items.filter(i=>i.id===requests[0].id).length,1);
    await owner.evaluate(()=>{document.querySelector('main').scrollTop=0;document.getElementById('toast').hidden=true;});
    await owner.screenshot({path:'output/playwright/display-announcements.png',animations:'disabled'});
    await owner.locator('[data-announcement-cancel="'+requests[0].id+'"]').click();
    await owner.waitForFunction(()=>document.getElementById('announcement-history').textContent.includes('Cancelled'));
    await owner.setViewportSize({width:390,height:844});
    assert.ok(await owner.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await owner.screenshot({path:'output/playwright/display-announcements-phone.png',fullPage:true,animations:'disabled'});

    const display=await browser.newPage({viewport:{width:1024,height:600}}),receipts=[];let messageId='d'.repeat(32),claimed=false,delivered=false;
    display.on('pageerror',e=>errors.push(e.message));
    await display.addInitScript(()=>{
      window.audioStarts=0;window.audioStops=0;window.audioNodes=[];
      window.AudioContext=class{constructor(){this.state='suspended';this.destination={};}async resume(){this.state='running';}createGain(){return{gain:{value:0},connect(){}};}async decodeAudioData(){return{};}createBufferSource(){const node={connect(){},start(){window.audioStarts++;},stop(){window.audioStops++;},onended:null};window.audioNodes.push(node);return node;}};
      HTMLMediaElement.prototype.play=()=>{throw Error('Real audio forbidden');};
    });
    await display.route('**/*',route=>{
      const r=route.request(),url=new URL(r.url());if(url.origin!==base)return route.abort();
      if(url.pathname==='/v1/display/session')return route.fulfill({json:{role:'display',receiver_id:'a'.repeat(32)}});
      const inbox=ready=>({enabled:true,ready,status:ready?'ready':'sound_off',items:ready&&!claimed&&!delivered?[{id:messageId,title:'Dinner',message:'A sample message'}]:[],active:claimed?[{id:messageId,status:delivered?'played':'claimed'}]:[]});
      if(url.pathname==='/v1/audio/receiver')return route.fulfill({json:inbox(r.postDataJSON().ready&&!r.postDataJSON().busy)});
      if(url.pathname==='/v1/audio/inbox')return route.fulfill({json:inbox(true)});
      if(url.pathname.endsWith('/claim')){claimed=true;return route.fulfill({json:{claim:'c'.repeat(64)}});}
      if(url.pathname.endsWith('/audio'))return route.fulfill({contentType:'audio/wav',body:Buffer.alloc(48)});
      if(url.pathname.endsWith('/receipt')){receipts.push(r.postDataJSON());delivered=true;return route.fulfill({json:{status:r.postDataJSON().status}});}
      return route.continue();
    });
    await display.goto(base+'/display#settings');await display.locator('#announcement-listen').waitFor();
    await display.evaluate(()=>pollAnnouncements());assert.equal(await display.evaluate(()=>window.audioStarts),0);
    await display.locator('#announcement-listen').click();await display.waitForFunction(()=>window.audioStarts===1);
    await display.evaluate(()=>window.audioNodes[0].onended());
    await display.waitForFunction(()=>!announceCurrent);assert.ok(receipts.some(r=>r.status==='played'));
    messageId='e'.repeat(32);claimed=false;delivered=false;
    await display.evaluate(()=>pollAnnouncements());await display.waitForFunction(()=>window.audioStarts===2);
    await display.evaluate(()=>{displayCaptureBusy=true;document.dispatchEvent(new Event('echo:audio-focus'));});
    await display.waitForFunction(()=>window.audioStops===1);
    await display.waitForTimeout(100);assert.ok(receipts.some(r=>r.status==='cancelled'));
    assert.deepEqual(errors,[]);
    console.log('Room assignments, send/retry/cancel, phone layout, opt-in receiver, playback receipt and voice interruption passed. Synthetic audio only.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});

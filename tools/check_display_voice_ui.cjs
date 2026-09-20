const {previewBase}=require('./display_check.cjs');
const {chromium}=require('playwright');const assert=require('node:assert/strict');
(async()=>{
  const base=await previewBase();
  const browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1024,height:600}});let uploads=0,available=true;
    await page.route('**/v1/display/voice',route=>{
      if(route.request().method()==='POST')uploads++;
      return route.fulfill({json:{available,max_seconds:8,mode:'push_to_talk'}});
    });
    await page.addInitScript(()=>{
      window.stoppedTracks=0;window.micPromises=[];window.audioPresent=true;
      Object.defineProperty(navigator,'mediaDevices',{value:{enumerateDevices:async()=>window.audioPresent?[{kind:'audioinput'}]:[],getUserMedia:()=>new Promise(resolve=>window.micPromises.push(()=>resolve({getTracks:()=>[{stop:()=>window.stoppedTracks++}]})))}});
      window.AudioContext=class{constructor(){throw new Error('Cancelled capture must never open an AudioContext');}};
    });
    await page.goto(base+'/display');
    const refreshPage=async()=>{await page.waitForFunction(()=>!polling);await page.evaluate(()=>refresh());};
    await page.getByRole('button',{name:'Echo',exact:true}).click();
    await page.locator('#voice-start').click();await page.locator('#voice-cancel').click();
    // A delayed permission reply from a cancelled attempt must close its tracks,
    // even if the user has already opened a second request.
    await page.locator('#voice-start').click();
    await page.evaluate(()=>window.micPromises[0]());
    await page.waitForFunction(()=>window.stoppedTracks===1);
    assert.match(await page.locator('#display-voice-status').innerText(),/Opening/);
    await page.getByRole('button',{name:'Home',exact:true}).click();
    await page.evaluate(()=>window.micPromises[1]());
    await page.waitForFunction(()=>window.stoppedTracks===2);
    await refreshPage();
    assert.equal(await page.locator('#display-voice-status').textContent(),'Microphone closed.');
    available=false;await refreshPage();
    assert.equal(await page.locator('#display-voice-status').textContent(),'Preview only · voice capture is off.');
    available=true;await refreshPage();
    assert.equal(await page.locator('#display-voice-status').textContent(),'Tap the microphone, or type a message.');
    await page.evaluate(async()=>{window.audioPresent=false;await detectMicrophone();});await refreshPage();
    assert.equal(await page.locator('#display-voice-status').textContent(),'No microphone detected. You can still type.');
    await page.evaluate(async()=>{window.audioPresent=true;await detectMicrophone();});await refreshPage();
    assert.equal(await page.locator('#display-voice-status').textContent(),'Tap the microphone, or type a message.');
    assert.equal(uploads,0);
    console.log('Passed: delayed microphone grants close; service/microphone recovery clears stale availability messages; cancellation status retained; no AudioContext or uploads.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});

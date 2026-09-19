const {chromium}=require('playwright');const assert=require('node:assert/strict');
(async()=>{
  const browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1024,height:600}});let uploads=0;
    await page.route('**/v1/display/voice',route=>{
      if(route.request().method()==='POST')uploads++;
      return route.fulfill({json:{available:true,max_seconds:8,mode:'push_to_talk'}});
    });
    await page.addInitScript(()=>{
      window.stoppedTracks=0;window.micPromises=[];
      Object.defineProperty(navigator,'mediaDevices',{value:{getUserMedia:()=>new Promise(resolve=>window.micPromises.push(()=>resolve({getTracks:()=>[{stop:()=>window.stoppedTracks++}]})))}});
      window.AudioContext=class{constructor(){throw new Error('Cancelled capture must never open an AudioContext');}};
    });
    await page.goto('http://127.0.0.1:8788/display');
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
    assert.equal(uploads,0);
    console.log('Passed: cancel/navigation closes delayed microphone grants, no AudioContext opened, no recordings uploaded.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});

/* Silent, synthetic display acceptance. Requires a separately running preview. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

(async()=>{
  const output=path.resolve('output/playwright');fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1024,height:600}}),errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/*',route=>new URL(route.request().url()).hostname==='127.0.0.1' ? route.continue() : route.abort());
    await page.goto('http://127.0.0.1:8788/display');
    await page.getByRole('button',{name:'Planner',exact:true}).click();
    await page.locator('#schedule-title').fill('Morning routine reminder');
    await page.locator('#schedule-time').fill('07:30');await page.locator('#schedule-repeat').selectOption('daily');
    await page.getByRole('button',{name:'Save schedule',exact:true}).click();
    await page.locator('#schedule-list').getByText('Morning routine reminder',{exact:true}).first().waitFor();
    await page.evaluate(()=>document.querySelector('main').scrollTop=0); await page.locator('#toast').waitFor({state:'hidden',timeout:10000}); await page.screenshot({path:path.join(output,'display-planner.png'),animations:'disabled',style:'#toast{visibility:hidden}'});
    await page.locator('#notice-message').fill('Dinner is ready when you are.');
    assert.equal(await page.locator('#notice-announce').isChecked(),false);
    await page.getByRole('button',{name:'Send message',exact:true}).click();
    await page.locator('#schedule-events').getByText('Dinner is ready when you are.',{exact:true}).first().waitFor();
    await page.getByRole('button',{name:'Lists',exact:true}).click();
    await page.locator('#household-items [data-edit-item]').first().click();
    await page.locator('#list-edit-text').fill('Fresh coffee beans');await page.getByRole('button',{name:'Save item',exact:true}).click();
    await page.locator('#household-items').getByText('Fresh coffee beans',{exact:true}).waitFor();
    await page.getByRole('button',{name:'My day',exact:true}).click();
    await page.getByText('Dinner with friends',{exact:true}).waitFor();
    await page.locator('#toast').waitFor({state:'hidden',timeout:10000}); await page.screenshot({path:path.join(output,'display-agenda.png'),animations:'disabled',style:'#toast{visibility:hidden}'});
    await page.getByRole('button',{name:'Settings',exact:true}).click();
    await page.getByRole('button',{name:'Load sources',exact:true}).click();
    await page.locator('#source-choices input[value="camera.porch_demo"]').uncheck();
    await page.getByRole('button',{name:'Save display sources',exact:true}).click();
    await page.locator('#toast').getByText('Display sources saved.',{exact:true}).waitFor();
    await page.locator('#album-upload').setInputFiles({name:'synthetic-pixel.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=','base64')});
    await page.locator('#album-grid img').first().waitFor();
    await page.locator('#album-grid [data-delete-photo]').first().click();
    await page.waitForFunction(()=>document.querySelectorAll('#album-grid img').length===0);
    await page.setViewportSize({width:390,height:844});
    await page.getByRole('button',{name:'My day',exact:true}).click();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.locator('#toast').waitFor({state:'hidden',timeout:10000}); await page.screenshot({path:path.join(output,'display-agenda-phone.png'),animations:'disabled',style:'#toast{visibility:hidden}'});
    assert.deepEqual(errors,[]);
    console.log('Passed: recurring schedule, silent notification, list edit, agenda, source selection, photo upload/delete, phone layout; no external requests or playback.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});

const {previewBase}=require('./display_check.cjs');
/* Synthetic daily overview and calendar forms; never writes a real calendar. */
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
  const base=await previewBase();
  fs.mkdirSync('output/playwright',{recursive:true});const browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1024,height:600}}),errors=[];let sent,created=0;
    page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/*',route=>new URL(route.request().url()).hostname==='127.0.0.1'?route.continue():route.abort());
    await page.route('**/v1/display/calendar/events',route=>{sent=route.request().postDataJSON();created++;return route.continue();});
    await page.goto(base+'/display#day');
    await page.locator('#briefing-summary').getByText(/room to breathe/).waitFor();
    await page.screenshot({path:'output/playwright/display-daily.png',animations:'disabled'});
    await page.locator('#calendar-create').click();
    await page.locator('.calendar-draft-composer summary').click();
    await page.locator('#calendar-draft-text').fill('Lunch with Sam tomorrow at noon for an hour');
    await page.locator('#calendar-draft-build').click();await page.locator('#calendar-event-status').getByText('Draft only.',{exact:false}).waitFor();
    assert.equal(created,0);assert.equal(await page.locator('#event-title').inputValue(),'Lunch with Sam · sample');
    assert.match(await page.locator('#event-start').inputValue(),/T12:00$/);
    await page.screenshot({path:'output/playwright/display-calendar-draft.png',animations:'disabled'});
    await page.locator('#event-title').fill('An afternoon outside · sample');
    await page.locator('#event-start').fill('2026-09-23T14:00');await page.locator('#event-end').fill('2026-09-23T15:00');
    await page.locator('#event-timezone').fill('America/New_York');await page.locator('#event-location').fill('The park');
    await page.screenshot({path:'output/playwright/display-calendar-event.png',animations:'disabled'});
    await page.locator('#calendar-event-submit').click();await page.locator('#calendar-event-status').getByText('Demo event created. No real calendar was changed.').waitFor();
    assert.equal(sent.event.start,'2026-09-23T14:00');assert.equal(sent.event.timezone,'America/New_York');assert.match(sent.request_id,/^[a-f0-9]{32}$/);
    assert.ok(await page.locator('#calendar-event-submit').isDisabled());await page.locator('#calendar-event-cancel').click();
    await page.locator('#calendar-create').click();await page.locator('#event-title').fill('All-day sample');await page.locator('#event-all-day').check();
    await page.locator('#event-start').fill('2026-09-24');await page.locator('#event-end').fill('2026-09-24');
    await page.locator('#calendar-event-submit').click();await page.locator('#calendar-event-status').getByText('Demo event created. No real calendar was changed.').waitFor();
    assert.equal(sent.event.end,'2026-09-25');assert.equal(sent.event.all_day,true);await page.locator('#calendar-event-cancel').click();
    await page.getByRole('button',{name:'Echo',exact:true}).click();await page.locator('#chat-text').fill('Add lunch tomorrow to my calendar');
    await page.locator('#chat-form button[type="submit"]').click();
    await page.getByRole('button',{name:'Review calendar draft'}).click();
    assert.equal(created,2);assert.equal(await page.locator('#event-title').inputValue(),'Lunch with Sam · sample');
    await page.locator('#calendar-event-cancel').click();
    await page.locator('.rail-settings').click();await page.locator('#source-load').click();
    const read=page.locator('[data-source-read][value="calendar.household_demo"]'),write=page.locator('[data-source-write][value="calendar.household_demo"]');
    await read.uncheck();assert.equal(await write.isChecked(),false);await write.check();assert.equal(await read.isChecked(),true);
    await page.locator('#source-form button[type="submit"]').click();await page.locator('#toast').getByText('Display sources saved.').waitFor();
    await page.locator('[data-page="day"]').click();await page.setViewportSize({width:390,height:844});
    await page.locator('#calendar-create').click();await page.locator('#event-title').fill('Phone-sized event form');
    await page.screenshot({path:'output/playwright/display-calendar-phone.png',fullPage:true,animations:'disabled'});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    const dialog=await page.locator('#calendar-event-dialog').boundingBox();assert.ok(dialog.x>=0&&dialog.x+dialog.width<=390);
    assert.deepEqual(errors,[]);console.log('Calendar drafts from form/chat, explicit creation, timed/all-day forms, permissions and phone layout passed. Synthetic calendar only.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

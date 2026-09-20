/* Synthetic owner/guest UI. Server permission behavior is covered by the real API tests. */
const {previewBase}=require('./display_check.cjs');
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
  const base=await previewBase(),browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1024,height:600},hasTouch:true}),errors=[];let saved=null;
    page.on('pageerror',e=>{errors.push(e.message);console.error(e.stack);});
    const profile={mode:'household',name:'Household',room:'',conversation:true,home_devices:{},calendars:[],cameras:[],presence_sensors:[]};
    const display={id:'a'.repeat(32),name:'Guest room display',profile,profile_revision:0};
    await page.route('**/v1/displays',r=>r.fulfill({json:{items:[display]}}));
    await page.route('**/v1/displays/*/profile',r=>{saved=r.request().postDataJSON();display.profile=saved.profile;display.profile_revision++;return r.fulfill({json:{profile:display.profile,profile_revision:display.profile_revision}});});
    await page.goto(base+'/display#settings');await page.locator('[data-profile-display]').tap();
    try{await page.locator('#display-access-save:not(:disabled)').waitFor({timeout:5000});}catch(error){console.error(await page.locator('#display-access-status').textContent());throw error;}
    await page.locator('#display-access-mode').selectOption('guest');
    await page.locator('#display-access-name').fill('Visiting friends');await page.locator('#display-access-room').fill('Guest room');
    // Close the soft keyboard to review the complete grant list.
    await page.locator('#display-access-mode').selectOption('guest');
    const lamp=page.locator('[data-profile-entity]').first();const entity=await lamp.getAttribute('data-profile-entity');
    await lamp.selectOption('read');await page.locator('[data-profile-source=calendars]').first().check();
    await page.locator('[data-profile-source=cameras]').first().check();
    fs.mkdirSync('output/playwright',{recursive:true});
    await page.screenshot({path:'output/playwright/display-access-profile.png',animations:'disabled'});
    assert.equal(saved,null);await page.locator('#display-access-save').tap();await page.locator('#display-access-dialog').waitFor({state:'hidden'});
    assert.equal(saved.revision,0);assert.equal(saved.profile.mode,'guest');assert.equal(saved.profile.home_devices[entity],'read');
    assert.equal(saved.profile.home_voice,false);
    assert.deepEqual(saved.profile.calendars,['calendar.household_demo']);
    assert.deepEqual(saved.profile.cameras,['camera.porch_demo']);
    const guest=await browser.newPage({viewport:{width:1024,height:600},hasTouch:true});guest.on('pageerror',e=>errors.push(e.message));
    await guest.route('**/v1/display/session',r=>r.fulfill({json:{role:'display',receiver_id:display.id,profile_revision:1,profile:display.profile}}));
    for(const path of ['/v1/household','/v1/schedules','/v1/routines','/v1/display/photos','/v1/display/briefing*','/v1/voice'])
      await guest.route('**'+path,r=>r.fulfill({status:403,json:{detail:'Not shared with this guest display'}}));
    await guest.goto(base+'/display#lists');await guest.locator('body.guest-display').waitFor();
    await guest.waitForURL('**#home');assert.equal(await guest.locator('nav [data-page=lists]').isVisible(),false);
    await guest.locator('nav [data-page=rooms]').tap();assert.equal(await guest.locator('#room-cards').isVisible(),false);
    assert.equal(await guest.locator('#guest-display-note').isVisible(),true);
    await guest.locator('nav [data-page=day]').tap();assert.equal(await guest.locator('#calendar-create').isVisible(),false);
    assert.equal(await guest.locator('.daily-briefing').isVisible(),false);
    await guest.locator('nav [data-page=assistant]').tap();assert.equal(await guest.locator('#allow-home').isVisible(),false);
    assert.equal(await guest.locator('#send-chat').isEnabled(),true);
    await guest.screenshot({path:'output/playwright/display-guest-conversation.png',animations:'disabled'});
    let chat=null;
    await guest.route('**/v1/chat',r=>{chat=r.request().postDataJSON();return r.fulfill({json:{status:'complete',capability:'home',text:'Synthetic guest command handled.',access_revision:2}});});
    await guest.route('**/v1/display/session',r=>r.fulfill({json:{role:'display',receiver_id:display.id,profile_revision:2,profile:{...display.profile,home_voice:true}}}));
    await guest.reload();await guest.locator('body.guest-home-voice').waitFor();
    assert.equal(await guest.locator('#allow-home').isVisible(),true);
    await guest.locator('#allow-home').check();await guest.locator('#chat-text').fill('Turn off Guest lamp');
    await guest.locator('#send-chat').tap();await guest.getByText('Synthetic guest command handled.',{exact:true}).waitFor();
    assert.equal(chat.allow_home_actions,true);assert.equal(await guest.locator('#allow-home').isChecked(),false);
    await page.setViewportSize({width:390,height:844});await page.locator('[data-profile-display]').tap();
    await page.locator('#display-access-save:not(:disabled)').waitFor();
    const bounds=await page.locator('#display-access-dialog').boundingBox();assert.ok(bounds.x>=0&&bounds.x+bounds.width<=390&&bounds.y+bounds.height<=844);
    assert.deepEqual(errors,[]);console.log('PASS: explicit owner grants, guest navigation/privacy labels, optional home voice consent and phone profile editor.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

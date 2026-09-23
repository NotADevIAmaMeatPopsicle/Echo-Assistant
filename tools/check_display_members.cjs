/* Silent synthetic member UI; real authorization is tested in test_members.py. */
const {previewBase}=require('./display_check.cjs');
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
  const base=await previewBase(),browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1024,height:600},hasTouch:true}),errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    const profile={mode:'guest',name:'Alex',room:'',conversation:true,home_voice:false,home_devices:{},calendars:[],cameras:[],presence_sensors:[],members:[]};
    const account={id:'a'.repeat(32),name:'Alex',profile,revision:0};let items=[],personal=false,revision=0,memory=[],savedProfile;
    await page.route('**/v1/members',async r=>{if(r.request().method()==='POST'){items=[account];return r.fulfill({json:{...account,passcode:'12345678'}});}return r.fulfill({json:{items}});});
    await page.route('**/v1/members/available',r=>r.fulfill({json:{items,session_minutes:15}}));
    await page.route('**/v1/members/*/profile',r=>{savedProfile=r.request().postDataJSON();return r.fulfill({json:{revision:1}});});
    await page.route('**/v1/member/session',r=>{
      if(r.request().method()==='DELETE'){personal=false;revision++;return r.fulfill({json:{locked:true}});}
      if(r.request().postDataJSON().passcode!=='12345678')return r.fulfill({status:401,json:{detail:'Passcode was not accepted'}});
      personal=true;revision++;return r.fulfill({json:{profile_revision:revision,profile:{...profile,personal:true}}});
    });
    await page.route('**/v1/display/session',r=>r.fulfill({json:personal?{role:'display',receiver_id:'b'.repeat(32),profile_revision:revision,profile:{...profile,personal:true},member:{id:account.id,name:account.name,expires_at:Date.now()/1000+900}}:{role:'owner',profile_revision:revision}}));
    await page.route('**/v1/member/preferences',r=>r.fulfill({json:{personality:'Keep it friendly.',memory_enabled:true}}));
    await page.route('**/v1/memory',r=>{if(r.request().method()==='POST')memory.push({id:'c'.repeat(32),text:r.request().postDataJSON().text});return r.fulfill({json:{items:memory,scope:'personal'}});});
    await page.route('**/v1/memory/*',r=>{memory=[];return r.fulfill({json:{status:'deleted'}});});
    await page.goto(base+'/display#settings');await page.locator('#manage-members').tap();
    await page.locator('#member-name').fill('Alex');await page.locator('#member-create button').tap();
    await page.locator('#member-new-code').waitFor();assert.equal(await page.locator('#member-new-code').textContent(),'12345678');
    await page.locator('#member-code-done').tap();assert.equal(await page.locator('#member-new-code').count(),0);
    await page.locator('.member-row button').filter({hasText:'Access'}).tap();await page.locator('#display-access-save:not(:disabled)').waitFor();
    assert.equal(await page.locator('#display-access-mode option[value=household]').evaluate(el=>el.disabled),true);
    assert.equal(await page.locator('#display-access-members').isVisible(),false);
    await page.locator('#display-access-save').tap();await page.locator('#display-access-dialog').waitFor({state:'hidden'});assert.equal(savedProfile.profile.mode,'guest');
    await page.reload();await page.locator('#member-button').tap();await page.locator('#member-keypad').waitFor();
    for(const digit of '11111111')await page.locator('#member-keypad button').getByText(digit,{exact:true}).tap();
    await page.locator('#member-unlock').tap();await page.getByText('Passcode was not accepted',{exact:true}).waitFor();
    assert.equal(await page.locator('#member-code').inputValue(),'');assert.ok(await page.locator('#connection').isHidden());
    fs.mkdirSync('output/playwright',{recursive:true});await page.screenshot({path:'output/playwright/member-sign-in.png'});
    for(const digit of '12345678')await page.locator('#member-keypad button').getByText(digit,{exact:true}).tap();
    await page.locator('#member-unlock').tap();await page.locator('#member-button').filter({hasText:'Alex'}).waitFor();
    assert.equal(await page.locator('#members-card').isVisible(),false);assert.equal(await page.locator('nav [data-page=lists]').isVisible(),false);
    await page.locator('#member-button').tap();await page.locator('#member-fact').fill('I enjoy astronomy');await page.locator('#member-fact-form button').tap();
    await page.locator('.member-fact').waitFor();assert.equal(memory[0].text,'I enjoy astronomy');
    await page.locator('#member-close').focus();await page.keyboard.press('Escape');await page.locator('#member-button').tap();
    await page.screenshot({path:'output/playwright/member-memory.png'});
    await page.setViewportSize({width:390,height:844});
    const overflow=await page.evaluate(()=>[...document.querySelectorAll('body *')].filter(e=>{const r=e.getBoundingClientRect();return r.width&&r.right>innerWidth+1;}).map(e=>({id:e.id,tag:e.tagName,right:e.getBoundingClientRect().right})).slice(0,12));
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,JSON.stringify(overflow));
    await page.locator('.member-fact button').tap();await page.getByText('Nothing saved yet.',{exact:false}).waitFor();
    await page.locator('#member-lock').tap();await page.locator('#member-button').filter({hasText:'Sign in'}).waitFor();
    assert.equal(await page.locator('#member-content').textContent(),'');
    assert.equal(await page.evaluate(()=>Object.values(localStorage).some(v=>v.includes('12345678')||v.includes('astronomy'))),false);
    assert.deepEqual(errors,[]);console.log('Personal account creation, grants, keypad, wrong code, memory, lock and phone layout passed. No physical audio or home actions.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

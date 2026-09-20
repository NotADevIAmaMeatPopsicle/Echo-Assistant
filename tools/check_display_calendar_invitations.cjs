/* Entirely local, synthetic UI harness. No server, provider, microphone or audio. */
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..');
(async()=>{
  const browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1024,height:600}}),errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/*',route=>route.abort());
    await page.setContent('<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><main><h1>Synthetic calendar</h1></main></body></html>');
    await page.addStyleTag({path:path.join(root,'web/display/display.css')});
    await page.addStyleTag({path:path.join(root,'web/display/calendar-invitations.css')});
    await page.addScriptTag({content:`
      const data={session:{role:'owner',profile_revision:0,profile:{mode:'household'}},sources:{revision:1}},extensions=[];
      let signInRequired=false;
      const item={title:'Synthetic appointment',invitation_reference:{calendar:'calendar.synthetic',uid:'example',on_date:'2026-09-22',version:'a'.repeat(64)}};
      window.calls=[];window.failConfirm=true;window.holdRead=false;
      const guests=[{email:'owner@example.com',display_name:'Organizer',response_status:'accepted',protected:true},
        {email:'keep@example.com',response_status:'tentative',optional:true},{email:'remove@example.com',response_status:'accepted',resource:true}];
      const effect={all:'Google sends notifications to all guests, including new invitations and cancellations.',
        externalOnly:'Only guests who do not use Google Calendar receive notifications. Google decides which guests qualify.',
        none:'Requests no notifications. Some emails may still be sent and guests may lose synchronization.'};
      async function api(url,body){
        calls.push({url,body:structuredClone(body)});
        if(url.endsWith('/read')){
          if(holdRead)await new Promise(resolve=>window.releaseRead=resolve);
          return {read_id:'b'.repeat(32),expires_at:Date.now()/1000+300,attendees:structuredClone(guests),notification_choices:effect,
            event:{title:item.title,start:{dateTime:'2026-09-22T10:00:00-04:00'},end:{dateTime:'2026-09-22T11:00:00-04:00'},scope:'occurrence'}};
        }
        if(url.endsWith('/review'))return {review_id:'c'.repeat(32),review_proof:'d'.repeat(64),request_id:'e'.repeat(32),reference:item.invitation_reference,revision:1,
          expires_at:Date.now()/1000+300,added:body.add,removed:body.remove,attendees:[...guests.filter(g=>!body.remove.includes(g.email)),...body.add.map(email=>({email}))],
          send_updates:body.send_updates,notification_effect:effect[body.send_updates]};
        if(url.endsWith('/confirm')){
          if(failConfirm){failConfirm=false;throw Object.assign(Error('Synthetic uncertain response'),{status:503});}
          return {status:'accepted',text:'Synthetic guest change accepted. Delivery is not verified.'};
        }
        throw Error('Unexpected harness request');
      }
      HTMLMediaElement.prototype.play=()=>{throw Error('Audio is disabled in this check');};
    `});
    await page.addScriptTag({path:path.join(root,'web/display/calendar-invitations.js')});
    const open=()=>page.evaluate(()=>openCalendarInvitations(item,{revision:1}));
    const count=()=>page.evaluate(()=>calls.filter(c=>c.url.endsWith('/confirm')).length);
    await open();
    assert.equal(await page.locator('#calendar-invitations-notifications').inputValue(),'');
    assert.equal(await page.locator('[data-remove-email="owner@example.com"]').count(),0);
    await page.locator('#calendar-invitations-add').fill('new@example.com');
    await page.locator('[data-remove-email="remove@example.com"]').check();
    await page.locator('#calendar-invitations-notifications').selectOption('all');
    await page.locator('#calendar-invitations-submit').click();
    await page.locator('#calendar-invitations-review').waitFor({state:'visible'});
    assert.equal(await count(),0);assert.ok(await page.locator('#calendar-invitations-submit').isDisabled());
    assert.match(await page.locator('#calendar-invitations-changes').innerText(),/Keep \(2\)/);
    fs.mkdirSync(path.join(root,'output/playwright'),{recursive:true});
    await page.screenshot({path:path.join(root,'output/playwright/display-calendar-invitations.png')});
    await page.locator('#calendar-invitations-ack').check();await page.locator('#calendar-invitations-submit').click();
    await page.getByRole('button',{name:'Retry same request',exact:true}).waitFor();
    await page.locator('#calendar-invitations-submit').click();
    await page.locator('#calendar-invitations-status').getByText('Synthetic guest change accepted. Delivery is not verified.').waitFor();
    const confirmations=await page.evaluate(()=>calls.filter(c=>c.url.endsWith('/confirm')).map(c=>c.body));
    assert.equal(confirmations.length,2);assert.deepEqual(confirmations[0],confirmations[1]);assert.equal(confirmations[0].confirmed,true);
    assert.equal(confirmations[0].review_proof,'d'.repeat(64));
    await page.locator('#calendar-invitations-cancel').click();await page.setViewportSize({width:390,height:844});await open();
    assert.ok(await page.locator('#calendar-invitations-ack').isEnabled());
    await page.locator('#calendar-invitations-add').fill('other@example.com');
    await page.locator('#calendar-invitations-notifications').selectOption('none');
    assert.match(await page.locator('#calendar-invitations-effect').innerText(),/Some emails may still be sent/);
    await page.locator('#calendar-invitations-submit').click();
    await page.locator('#calendar-invitations-review').waitFor({state:'visible'});
    const bounds=await page.locator('#calendar-invitations-dialog').boundingBox();
    assert.ok(bounds.x>=0&&bounds.x+bounds.width<=390&&bounds.y>=0&&bounds.y+bounds.height<=844);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.screenshot({path:path.join(root,'output/playwright/display-calendar-invitations-phone.png')});
    await page.locator('#calendar-invitations-back').click();
    await page.locator('#calendar-invitations-notifications').selectOption('externalOnly');
    await page.locator('#calendar-invitations-submit').click();
    await page.locator('#calendar-invitations-review').waitFor({state:'visible'});
    assert.equal(await count(),2);
    await page.evaluate(()=>{data.session.profile_revision=1;extensions.forEach(fn=>fn());});
    assert.equal(await page.locator('#calendar-invitations-dialog').isVisible(),false);
    await page.evaluate(()=>{holdRead=true;void openCalendarInvitations(item,{revision:1});});
    await page.waitForFunction(()=>typeof releaseRead==='function');
    await page.evaluate(()=>{data.session.profile.mode='guest';extensions.forEach(fn=>fn());releaseRead();});
    await page.waitForTimeout(50);
    assert.equal(await page.locator('#calendar-invitations-dialog').isVisible(),false);
    await open();assert.equal(await page.locator('#calendar-invitations-dialog').isVisible(),false);
    assert.equal(await count(),2);assert.deepEqual(errors,[]);
    console.log('PASS: explicit guest/notification review, preserved guest display, no send before acknowledgment, exact-request retry, change selection, phone layout, access cancellation and stale-read discard. Synthetic only.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});

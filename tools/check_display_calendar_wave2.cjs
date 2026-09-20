/* Full-page integration against the synthetic preview. Every write is intercepted. */
const {previewBase}=require('./display_check.cjs');
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
  const base=await previewBase(),browser=await chromium.launch({channel:'chrome',headless:true});
  let releaseFollowing=null;
  try{
    const agenda=await(await fetch(base+'/v1/display/agenda')).json(),sources=await(await fetch(base+'/v1/display/sources')).json();
    const sample=agenda.events[0],entity=sample.calendar;
    const occurrence={...sample,id:'c'.repeat(32),title:'Synthetic counted series',provider:'google',recurring:true,all_day:false,
      reference:{calendar:entity,uid:'occurrence_20260922',recurrence_id:'master',version:'1'.repeat(64),on_date:'2026-09-22'},
      invitation_reference:null,following_start_locked:false,change_scopes:{edit:['occurrence','following','series'],delete:['occurrence','following','series']}};
    const invitation={...sample,id:'d'.repeat(32),title:'Synthetic event with guests',provider:'google',recurring:false,
      reference:null,invitation_reference:{calendar:entity,uid:'invitation',version:'2'.repeat(64),on_date:'2026-09-22'},change_scopes:{edit:[],delete:[]}};
    const following={provider:'google',reference:{...occurrence.reference,following_version:'3'.repeat(64)},prior_count:3,remaining_count:7,
      following_start_locked:false,editor_event:{calendar:entity,title:occurrence.title,description:'Preserve earlier events',location:'Studio',all_day:false,
        timezone:'America/New_York',start:'2026-09-22T10:00',end:'2026-09-22T11:00',start_fold:0,end_fold:0},repeat_summary:'RRULE:FREQ=WEEKLY;COUNT=7'};
    const guests=[{email:'keep@example.com',display_name:'Retained guest',response_status:'accepted'},
      {email:'remove@example.com',response_status:'tentative'}];
    const event={title:invitation.title,start:{dateTime:sample.start},end:{dateTime:sample.end},scope:'single'};
    const effect='Google sends notifications to all guests, including invitations and cancellations.';
    const page=await browser.newPage({viewport:{width:1024,height:600},hasTouch:true});
    const errors=[],changes=[],invitationCalls=[],followingReads=[];let guest=false,delayFollowing=null;
    page.on('pageerror',error=>errors.push(error.message));
    await page.addInitScript(()=>{
      Object.defineProperty(navigator,'mediaDevices',{value:{enumerateDevices:async()=>[],addEventListener(){},getUserMedia(){throw Error('No microphone in this check');}}});
      HTMLMediaElement.prototype.play=()=>{throw Error('No playback in this check');};
    });
    await page.route('**/*',async route=>{
      const request=route.request(),url=new URL(request.url());if(url.origin!==base)return route.abort();
      if(url.pathname==='/v1/display/session')return route.fulfill({json:guest?
        {role:'display',receiver_id:'a'.repeat(32),profile_revision:1,profile:{mode:'guest',name:'Guest',conversation:true}}:
        {role:'owner',profile_revision:0,profile:{mode:'household'}}});
      if(url.pathname==='/v1/display/sources'){
        const body=structuredClone(sources);body.revision=1;
        for(const item of body.items)if(item.entity_id===entity)item.writable=item.editable=item.deletable=!guest;
        return route.fulfill({json:body});
      }
      if(url.pathname==='/v1/display/agenda')return route.fulfill({json:{...agenda,events:[occurrence,invitation]}});
      if(url.pathname==='/v1/display/calendar/following'){
        followingReads.push(request.postDataJSON());assert.equal(followingReads.at(-1).reference.uid,occurrence.reference.uid);
        if(delayFollowing)await delayFollowing;
        return route.fulfill({json:following});
      }
      if(url.pathname==='/v1/display/calendar/change'){
        changes.push(request.postDataJSON());return route.fulfill({json:{status:'accepted',text:'Synthetic following change accepted.'}});
      }
      if(url.pathname.startsWith('/v1/display/calendar/invitations/')){
        const action=url.pathname.split('/').at(-1),body=request.postDataJSON();invitationCalls.push({action,body});
        if(action==='read')return route.fulfill({json:{read_id:'4'.repeat(32),event,attendees:guests,notification_choices:{all:effect},expires_at:Date.now()/1000+300}});
        if(action==='review')return route.fulfill({json:{review_id:'5'.repeat(32),review_proof:'6'.repeat(64),request_id:'7'.repeat(32),
          reference:invitation.invitation_reference,revision:1,event,attendees:[guests[0],{email:body.add[0]}],added:body.add,removed:body.remove,
          send_updates:body.send_updates,notification_effect:effect,expires_at:Date.now()/1000+300}});
        if(action==='confirm')return route.fulfill({json:{status:'accepted',text:'Synthetic guest change accepted.'}});
        throw Error('Unexpected invitation endpoint');
      }
      if(request.method()!=='GET'&&request.method()!=='HEAD'){
        assert.ok(!url.pathname.startsWith('/v1/display/calendar/'),'Unmocked calendar write: '+url.pathname);
        return route.fulfill({json:{status:'synthetic'}});
      }
      return route.continue();
    });
    await page.goto(base+'/display#day');
    const open=async id=>page.locator('[data-event-id="'+id+'"]').tap();
    await open(invitation.id);assert.equal(await page.locator('#calendar-details-edit').isVisible(),false);
    await page.locator('#calendar-details-invitations').tap();await page.locator('#calendar-invitations-fields').waitFor({state:'visible'});
    await page.locator('#calendar-invitations-add').fill('new@example.com');await page.locator('[data-remove-email="remove@example.com"]').check();
    await page.locator('#calendar-invitations-notifications').selectOption('all');
    await page.locator('#calendar-invitations-submit').tap();await page.locator('#calendar-invitations-review').waitFor({state:'visible'});
    assert.deepEqual(invitationCalls.map(c=>c.action),['read','review']);assert.ok(await page.locator('#calendar-invitations-submit').isDisabled());
    assert.deepEqual(invitationCalls[1].body.remove,['remove@example.com']);assert.deepEqual(invitationCalls[1].body.add,['new@example.com']);
    await page.locator('#calendar-invitations-ack').check();await page.locator('#calendar-invitations-submit').tap();
    await page.locator('#calendar-invitations-status').getByText('Synthetic guest change accepted.').waitFor();
    assert.deepEqual(invitationCalls.map(c=>c.action),['read','review','confirm']);
    assert.equal(invitationCalls[2].body.review_proof,'6'.repeat(64));assert.equal(invitationCalls[2].body.confirmed,true);
    await page.locator('#calendar-invitations-cancel').tap();
    await open(occurrence.id);await page.locator('#calendar-details-edit').tap();
    assert.deepEqual(await page.locator('#calendar-change-scope option').evaluateAll(nodes=>nodes.map(n=>n.value)),['occurrence','following','series']);
    await page.locator('#calendar-change-scope').selectOption('following');assert.equal(followingReads.length,0);assert.equal(changes.length,0);
    await page.locator('#calendar-details-confirm').tap();await page.locator('#calendar-event-dialog').waitFor({state:'visible'});
    assert.equal(followingReads.length,1);assert.ok(await page.locator('#event-start').isEnabled());assert.ok(await page.locator('#event-end').isEnabled());
    assert.ok(await page.locator('#event-all-day').isDisabled());assert.match(await page.locator('#calendar-event-status').innerText(),/3 earlier.*7 occurrences/);
    await page.locator('#event-start').fill('2026-09-23T12:00');await page.locator('#event-end').fill('2026-09-23T13:00');
    await page.locator('#calendar-event-submit').tap();await page.locator('#calendar-event-status').getByText('Synthetic following change accepted.').waitFor();
    assert.equal(changes.length,1);assert.equal(changes[0].operation,'edit');assert.equal(changes[0].scope,'following');
    assert.equal(changes[0].reference.following_version,'3'.repeat(64));assert.equal(changes[0].event.start,'2026-09-23T12:00');
    await page.locator('#calendar-event-cancel').tap();
    await open(occurrence.id);await page.locator('#calendar-details-delete').tap();await page.locator('#calendar-change-scope').selectOption('following');
    await page.locator('#calendar-details-confirm').tap();await page.getByRole('button',{name:'Delete 7 occurrences',exact:true}).waitFor();
    assert.equal(followingReads.length,2);assert.equal(changes.length,1);
    assert.match(await page.locator('#calendar-details-status').innerText(),/3 earlier occurrences.*Nothing has been changed/);
    fs.mkdirSync('output/playwright',{recursive:true});await page.screenshot({path:'output/playwright/display-calendar-wave2.png',animations:'disabled'});
    await page.locator('#calendar-details-confirm').tap();await page.locator('#calendar-details-status').getByText('Synthetic following change accepted.').waitFor();
    assert.equal(changes.length,2);assert.equal(changes[1].operation,'delete');assert.equal(changes[1].scope,'following');
    assert.equal(changes[1].reference.following_version,'3'.repeat(64));await page.locator('#calendar-details-close').tap();
    delayFollowing=new Promise(resolve=>{releaseFollowing=resolve;});
    await open(occurrence.id);await page.locator('#calendar-details-edit').tap();await page.locator('#calendar-change-scope').selectOption('following');
    await page.locator('#calendar-details-confirm').tap();await page.locator('#calendar-details-status').getByText('Checking the remaining events and repeat count…').waitFor();
    await page.locator('#calendar-details-close').tap();const closedResponse=page.waitForResponse('**/v1/display/calendar/following');releaseFollowing();delayFollowing=null;
    await closedResponse;await page.waitForTimeout(100);assert.equal(await page.locator('#calendar-event-dialog').isVisible(),false);
    delayFollowing=new Promise(resolve=>{releaseFollowing=resolve;});
    await open(occurrence.id);await page.locator('#calendar-details-edit').tap();await page.locator('#calendar-change-scope').selectOption('following');
    await page.locator('#calendar-details-confirm').tap();await page.locator('#calendar-details-status').getByText('Checking the remaining events and repeat count…').waitFor();
    await page.evaluate(()=>{data.sources.revision=2;});const staleResponse=page.waitForResponse('**/v1/display/calendar/following');releaseFollowing();delayFollowing=null;
    await staleResponse;await page.waitForTimeout(100);assert.equal(await page.locator('#calendar-event-dialog').isVisible(),false);
    await page.locator('#calendar-details-close').tap();guest=true;await page.reload();await page.locator('body.guest-display').waitFor();
    await open(invitation.id);assert.equal(await page.locator('#calendar-details-invitations').isVisible(),false);await page.locator('#calendar-details-close').tap();
    await open(occurrence.id);assert.equal(await page.locator('#calendar-details-edit').isVisible(),false);assert.equal(await page.locator('#calendar-details-delete').isVisible(),false);
    assert.equal(changes.length,2);assert.equal(invitationCalls.filter(c=>c.action==='confirm').length,1);assert.deepEqual(errors,[]);
    console.log('PASS: full agenda invitation entry and explicit confirmation; following review, movable dates and proof-bound save; two-step following deletion; closed/stale read discard; Guest hides new controls. All writes mocked; no provider or audio.');
  }finally{releaseFollowing?.();await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});

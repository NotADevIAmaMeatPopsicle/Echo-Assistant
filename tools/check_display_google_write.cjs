/* Silent synthetic review only. Calendar writes and OAuth are intercepted. */
const {previewBase}=require('./display_check.cjs');
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
 const base=await previewBase(),browser=await chromium.launch({channel:'chrome',headless:true});
 try{
  const agenda=await (await fetch(base+'/v1/display/agenda')).json(),sources=await (await fetch(base+'/v1/display/sources')).json();
  const page=await browser.newPage({viewport:{width:1024,height:600},hasTouch:true}),errors=[],changes=[],consents=[];
  let guest=false,loseResponse=true,delayMaster=null;
  const sample=agenda.events[0],entity=sample.calendar;
  const occurrence={...sample,id:'c'.repeat(32),title:'Weekly studio',provider:'google',recurring:true,
   start:'2026-09-22T14:00:00+00:00',end:'2026-09-22T15:00:00+00:00',all_day:false,
   reference:{calendar:entity,uid:'occurrence_20260922',recurrence_id:'master',version:'1'.repeat(64),on_date:'2026-09-22'},
   change_scopes:{edit:['occurrence','series'],delete:['occurrence','series']}};
  const master={provider:'google',reference:{calendar:entity,uid:'master',version:'2'.repeat(64),on_date:'2026-09-01'},
   editor_event:{calendar:entity,title:'Original studio series',description:'Original notes',location:'Studio',all_day:false,
    timezone:'America/New_York',start:'2026-09-01T10:00',end:'2026-09-01T11:00',start_fold:0,end_fold:0},
   repeat_summary:'RRULE:FREQ=WEEKLY;COUNT=10'};
  page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(()=>{
   Object.defineProperty(navigator,'mediaDevices',{value:{enumerateDevices:async()=>[],addEventListener(){},getUserMedia(){throw Error('No microphone in this check');}}});
   HTMLMediaElement.prototype.play=()=>{throw Error('No playback in this check');};
  });
  await page.route('**/*',async route=>{
   const request=route.request(),url=new URL(request.url());
   if(url.origin!==base)return route.abort();
   if(url.pathname==='/v1/display/session')return route.fulfill({json:guest?{role:'display',receiver_id:'d'.repeat(32),profile_revision:1,profile:{mode:'guest',name:'Guest',conversation:true}}:{role:'owner'}});
   if(url.pathname==='/v1/calendar/google')return route.fulfill({json:{revision:1,client_id:'123-example.apps.googleusercontent.com',redirect_uri:'https://echo.example.com/v1/calendar/google/callback',secret_saved:true,enabled:true,accounts:[]}});
   if(url.pathname==='/v1/calendar/google/flows'){
    consents.push(request.postDataJSON());return route.fulfill({json:{id:'a'.repeat(32),url:'https://accounts.google.com/o/oauth2/v2/auth?state=synthetic',expires_at:Date.now()/1000+600}});
   }
   if(url.pathname.startsWith('/v1/calendar/google/flows/'))return route.fulfill({json:request.method()==='DELETE'?{cancelled:true}:{status:'waiting'}});
   if(url.pathname==='/v1/display/sources'){
    const body=structuredClone(sources);
    for(const item of body.items)if(item.entity_id===entity)item.writable=item.editable=item.deletable=!guest;
    return route.fulfill({json:body});
   }
   if(url.pathname==='/v1/display/agenda')return route.fulfill({json:{...agenda,events:[occurrence]}});
   if(url.pathname==='/v1/display/calendar/master'){
    assert.equal(request.postDataJSON().reference.uid,'occurrence_20260922');
    if(delayMaster)await delayMaster;
    return route.fulfill({json:master});
   }
   if(url.pathname==='/v1/display/calendar/change'){
    changes.push(request.postDataJSON());
    if(loseResponse){loseResponse=false;return route.abort('failed');}
    return route.fulfill({json:{status:'accepted',text:'Synthetic Google change accepted.'}});
   }
   if(request.method()!=='GET'&&request.method()!=='HEAD')return route.fulfill({json:{status:'synthetic'}});
   return route.continue();
  });
  await page.goto(base+'/display#settings');await page.locator('#google-load').click();
  assert.equal(await page.locator('#google-write-access').isChecked(),false);
  await page.waitForFunction(()=>data.health?.display_demo);
  await page.locator('#google-begin').click();assert.equal(consents.length,0);
  await page.evaluate(()=>{data.health.display_demo=false;});await page.locator('#google-begin').click();
  await page.locator('#google-flow').waitFor({state:'visible'});assert.equal(consents[0].write_access,false);
  await page.locator('#google-cancel').click();await page.locator('#google-write-access').check();
  await page.locator('#google-begin').click();await page.locator('#google-flow').waitFor({state:'visible'});
  assert.equal(consents[1].write_access,true);await page.locator('#google-cancel').click();
  await page.locator('[data-page="day"]').first().click();
  const open=async()=>page.locator('[data-event-id="'+'c'.repeat(32)+'"]').tap();
  await open();await page.locator('#calendar-details-edit').tap();
  assert.deepEqual(await page.locator('#calendar-change-scope option').evaluateAll(nodes=>nodes.map(n=>n.value)),['occurrence','series']);
  await page.locator('#calendar-change-scope').selectOption('series');await page.locator('#calendar-details-confirm').tap();
  await page.locator('#calendar-event-dialog').waitFor({state:'visible'});
  assert.equal(await page.locator('#event-start').inputValue(),'2026-09-01T10:00');
  assert.equal(await page.locator('#event-timezone').inputValue(),'America/New_York');
  assert.equal(await page.locator('#event-title').inputValue(),'Original studio series');
  assert.match(await page.locator('#calendar-event-status').textContent(),/COUNT=10/);
  assert.ok(await page.locator('#event-all-day').isDisabled());assert.ok(await page.locator('#event-start').isEnabled());
  await page.locator('#event-start').fill('2026-09-02T12:00');await page.locator('#event-end').fill('2026-09-02T13:00');
  await page.locator('#calendar-event-submit').tap();await page.getByRole('button',{name:'Retry same request',exact:true}).waitFor();
  await page.locator('#calendar-event-submit').tap();await page.locator('#calendar-event-status').getByText('Synthetic Google change accepted.').waitFor();
  assert.equal(changes.length,2);assert.deepEqual(changes[0],changes[1]);assert.equal(changes[0].reference.uid,'master');
  assert.equal(changes[0].scope,'series');assert.equal(changes[0].event.start,'2026-09-02T12:00');assert.equal(changes[0].event.recurrence,undefined);
  fs.mkdirSync('output/playwright',{recursive:true});await page.screenshot({path:'output/playwright/display-google-write.png',animations:'disabled'});
  await page.locator('#calendar-event-cancel').tap();
  let releaseMaster;delayMaster=new Promise(resolve=>{releaseMaster=resolve;});
  await open();await page.locator('#calendar-details-edit').tap();await page.locator('#calendar-change-scope').selectOption('series');
  await page.locator('#calendar-details-confirm').tap();await page.locator('#calendar-details-status').getByText('Loading the original series and its repeat pattern…').waitFor();
  await page.locator('#calendar-details-close').tap();releaseMaster();delayMaster=null;
  await page.waitForLoadState('networkidle');assert.equal(await page.locator('#calendar-event-dialog').isVisible(),false);
  await page.setViewportSize({width:390,height:844});await open();await page.locator('#calendar-details-delete').tap();
  await page.locator('#calendar-change-scope').selectOption('series');assert.match(await page.locator('#calendar-scope-note').textContent(),/past and future/);
  const bounds=await page.locator('#calendar-details-dialog').boundingBox();assert.ok(bounds.x>=0&&bounds.x+bounds.width<=390&&bounds.y+bounds.height<=844);
  await page.locator('#calendar-details-cancel').tap();assert.equal(changes.length,2);await page.locator('#calendar-details-close').tap();
  guest=true;await page.reload();await page.locator('body.guest-display').waitFor();await open();
  assert.equal(await page.locator('#calendar-details-edit').isVisible(),false);assert.equal(await page.locator('#calendar-details-delete').isVisible(),false);
  assert.equal(await page.locator('#google-calendar-card').isVisible(),false);assert.deepEqual(errors,[]);
  console.log('PASS: optional write consent, original-master fields, counted-series review, same-ID retry, cancelled-read discard, phone bounds and guest denial. Silent synthetic data only.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});

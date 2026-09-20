/* Synthetic recurrence controls; writes are intercepted and never reach a calendar. */
const {previewBase}=require('./display_check.cjs');
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
  const base=await previewBase(),browser=await chromium.launch({channel:'chrome',headless:true});
  const agenda=await (await fetch(base+'/v1/display/agenda')).json(),sources=await (await fetch(base+'/v1/display/sources')).json();
  try{
    const page=await browser.newPage({viewport:{width:1024,height:600},hasTouch:true}),errors=[],changes=[];
    let guest=false;
    page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/*',r=>new URL(r.request().url()).hostname==='127.0.0.1'?r.continue():r.abort());
    await page.route('**/v1/display/agenda*',async r=>{
      const body=structuredClone(agenda),sample=body.events[0];
      body.events=[{...sample,id:'c'.repeat(32),title:'Weekly studio time',recurring:true,following_start_locked:true,
        reference:{...sample.reference,uid:'synthetic-weekly-series',recurrence_id:'provider-occurrence-example'},
        change_scopes:{edit:['occurrence','following'],delete:['occurrence','following','series']}}];
      await r.fulfill({json:body});
    });
    await page.route('**/v1/display/sources',async r=>{
      const body=structuredClone(sources);
      if(guest)for(const item of body.items)item.writable=item.editable=item.deletable=false;
      await r.fulfill({json:body});
    });
    await page.route('**/v1/display/calendar/change',r=>{
      changes.push(r.request().postDataJSON());
      return r.fulfill({json:{status:'accepted',text:'Synthetic change accepted.'}});
    });
    await page.goto(base+'/display#day');
    const open=async()=>page.locator('[data-event-id="'+'c'.repeat(32)+'"]').tap();
    await open();await page.locator('#calendar-details-edit').tap();
    assert.deepEqual(await page.locator('#calendar-change-scope option').evaluateAll(nodes=>nodes.map(n=>n.value)),['occurrence','following']);
    await page.locator('#calendar-change-scope').selectOption('following');
    assert.equal(changes.length,0);await page.locator('#calendar-details-confirm').tap();
    assert.ok(await page.locator('#event-start').isDisabled());
    assert.ok(await page.locator('#event-all-day').isDisabled());
    assert.equal(await page.locator('.calendar-recurrence').isVisible(),false);
    await page.locator('#event-title').fill('Updated studio time');
    await page.locator('#calendar-event-submit').tap();
    await page.locator('#calendar-event-status').getByText('Synthetic change accepted.').waitFor();
    assert.equal(changes.length,1);assert.equal(changes[0].scope,'following');
    assert.equal(changes[0].reference.recurrence_id,'provider-occurrence-example');
    assert.equal(changes[0].event.recurrence,undefined);
    await page.locator('#calendar-event-cancel').tap();
    await open();await page.locator('#calendar-details-edit').tap();await page.locator('#calendar-details-confirm').tap();
    assert.ok(await page.locator('#event-start').isEnabled());assert.ok(await page.locator('#event-all-day').isEnabled());
    assert.equal(await page.locator('#calendar-event-submit').textContent(),'Save this occurrence');
    await page.locator('#calendar-event-cancel').tap();
    await open();await page.locator('#calendar-details-delete').tap();
    await page.locator('#calendar-change-scope').selectOption('series');
    assert.match(await page.locator('#calendar-scope-note').textContent(),/past and future/);
    assert.equal(changes.length,1);await page.locator('#calendar-details-cancel').tap();
    assert.equal(changes.length,1);await page.locator('#calendar-details-delete').tap();
    await page.locator('#calendar-change-scope').selectOption('series');
    fs.mkdirSync('output/playwright',{recursive:true});
    await page.screenshot({path:'output/playwright/display-calendar-series.png',animations:'disabled'});
    await page.locator('#calendar-details-confirm').tap();
    await page.locator('#calendar-details-status').getByText('Synthetic change accepted.').waitFor();
    assert.equal(changes.length,2);assert.equal(changes[1].scope,'series');assert.equal(changes[1].operation,'delete');
    await page.locator('#calendar-details-close').tap();
    await page.locator('#calendar-create').tap();
    assert.ok(await page.locator('#event-start').isEnabled());assert.ok(await page.locator('#event-all-day').isEnabled());
    await page.locator('#calendar-event-cancel').tap();
    await page.setViewportSize({width:390,height:844});await open();await page.locator('#calendar-details-delete').tap();
    const bounds=await page.locator('#calendar-details-dialog').boundingBox();assert.ok(bounds.x>=0&&bounds.x+bounds.width<=390&&bounds.y+bounds.height<=844);
    await page.screenshot({path:'output/playwright/display-calendar-series-phone.png',animations:'disabled'});
    await page.locator('#calendar-details-close').tap();
    guest=true;
    await page.route('**/v1/display/session',r=>r.fulfill({json:{role:'display',receiver_id:'d'.repeat(32),profile_revision:1,profile:{mode:'guest',name:'Guest',conversation:true}}}));
    await page.reload();await page.locator('body.guest-display').waitFor();await open();
    assert.equal(await page.locator('#calendar-details-edit').isVisible(),false);
    assert.equal(await page.locator('#calendar-details-delete').isVisible(),false);
    assert.equal(changes.length,2);assert.deepEqual(errors,[]);
    console.log('PASS: occurrence/following scope, count preservation controls, series deletion confirmation, form reset, guest denial and phone layout. Synthetic data only.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

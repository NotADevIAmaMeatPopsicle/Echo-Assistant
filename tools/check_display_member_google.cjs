/* Silent private calendar UI against the required synthetic loopback preview. */
const {previewBase}=require('./display_check.cjs');
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
  const base=await previewBase(),browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1024,height:600},hasTouch:true}),errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/*',route=>new URL(route.request().url()).hostname==='127.0.0.1'?route.continue():route.abort());
    const alice='a'.repeat(32),bob='b'.repeat(32),account='c'.repeat(32),entity='calendar.google_'+'d'.repeat(32)+'_'+'e'.repeat(24);
    let currentMember=alice,personal=true,connected=false,inventory=false,revision=0,selected=[],started=[],cancelled=0,late=null,delay=false;
    const expires=Date.now()/1000+900;
    const session=()=>({role:'display',receiver_id:'f'.repeat(32),profile_revision:1,
      profile:{mode:personal?'guest':'household',personal,name:currentMember===alice?'Alice':'Bob',conversation:true,home_voice:false,home_devices:{},calendars:[],cameras:[],presence_sensors:[],members:[]},
      ...(personal?{member:{id:currentMember,name:currentMember===alice?'Alice':'Bob',expires_at:expires}}:{})});
    const settings=()=>({enabled:true,configured:true,needs_reconnect:false,read_only:true,revision,
      accounts:connected?[{id:account,label:'Alice private connection',calendar_count:inventory?1:0}]:[],
      calendars:inventory?[{entity_id:entity,name:'Alice private calendar',account_label:'Alice private connection',timezone:'America/New_York',selected:selected.includes(entity)}]:[]});
    await page.route('**/v1/display/session',route=>route.fulfill({json:session()}));
    await page.route('**/v1/members/available',route=>route.fulfill({json:{items:[]}}));
    await page.route('**/v1/member/calendar/google**',async route=>{
      const request=route.request(),url=new URL(request.url()),path=url.pathname,method=request.method();
      if(path.endsWith('/google')&&method==='GET'){
        const body=settings();if(delay){delay=false;late=()=>route.fulfill({json:body});return;}
        return route.fulfill({json:body});
      }
      if(path.endsWith('/flows')&&method==='POST'){
        started.push(request.postDataJSON());return route.fulfill({json:{id:'1'.repeat(32),url:'https://accounts.google.com/o/oauth2/v2/auth?state=synthetic&scope=readonly',expires_at:expires}});
      }
      if(path.includes('/flows/')&&path.endsWith('/finish')){connected=true;revision++;return route.fulfill({json:{id:account,label:'Alice private connection',connected:true}});}
      if(path.includes('/flows/')&&method==='GET')return route.fulfill({json:{id:'1'.repeat(32),status:'approved',expires_at:expires}});
      if(path.includes('/flows/')&&method==='DELETE'){cancelled++;return route.fulfill({json:{cancelled:true}});}
      if(path.endsWith('/sync')){inventory=true;revision++;return route.fulfill({json:{calendar_count:1}});}
      if(path.endsWith('/selection')){const body=request.postDataJSON();assert.equal(body.revision,revision);selected=body.calendars;revision++;return route.fulfill({json:{revision,calendars:selected}});}
      if(path.includes('/accounts/')&&method==='DELETE'){connected=inventory=false;selected=[];revision++;return route.fulfill({json:{disconnected:true}});}
      throw Error('Unexpected synthetic private calendar route');
    });
    await page.goto(base+'/display#day');
    await page.locator('#member-google-button').waitFor({state:'visible'});
    await page.locator('#member-google-button').tap();
    await page.locator('#member-google-begin:not(:disabled)').waitFor();
    // The product preview still refuses real sign-in; this test alone enables
    // the mocked start button while every provider URL is blocked above.
    await page.evaluate(()=>{data.health.display_demo=false;});
    await page.locator('#member-google-label').fill('My private connection');
    await page.locator('#member-google-begin').tap();
    await page.locator('#member-google-signin[href]').waitFor();
    assert.equal(started.length,1);assert.deepEqual(Object.keys(started[0]).sort(),['client','label']);
    assert.match(started[0].client,/^[a-f0-9]{64}$/);
    assert.ok((await page.locator('#member-google-signin').getAttribute('href')).startsWith('https://accounts.google.com/'));
    await page.locator('#member-google-finish').waitFor({state:'visible'});
    await page.locator('#member-google-finish').tap();
    await page.locator('.member-google-calendar').filter({hasText:'Alice private calendar'}).waitFor();
    const checkbox=page.locator('#member-google-calendars input');
    assert.equal(await checkbox.isChecked(),false);assert.deepEqual(selected,[]);
    await checkbox.check();await page.locator('#member-google-save').tap();
    await page.getByText('Your private calendar selection was saved.',{exact:true}).waitFor();
    assert.deepEqual(selected,[entity]);
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    assert.equal(await page.locator('#member-google-dialog').evaluate(element=>element.scrollWidth<=element.clientWidth+1),true);
    fs.mkdirSync('output/playwright',{recursive:true});await page.screenshot({path:'output/playwright/member-google.png'});
    await page.locator('#member-google-close').tap();
    delay=true;await page.locator('#member-google-button').tap();
    for(let attempt=0;attempt<30&&!late;attempt++)await new Promise(resolve=>setTimeout(resolve,50));
    assert.ok(late,'Expected a held private settings request');
    currentMember=bob;
    await page.evaluate(({bob,expires})=>{data.session.member={id:bob,name:'Bob',expires_at:expires};},{bob,expires});
    await page.locator('#member-google-dialog').waitFor({state:'hidden'});
    await late();await page.waitForTimeout(100);
    assert.equal(await page.locator('#member-google-content').textContent(),'');
    assert.equal(await page.locator('.member-google-calendar').filter({hasText:'Alice private calendar'}).count(),0);
    personal=false;
    await page.evaluate(()=>{delete data.session.member;data.session.profile.personal=false;});
    await page.locator('#member-google-button').waitFor({state:'hidden'});
    assert.equal(await page.evaluate(()=>Object.values(localStorage).some(value=>value.includes('Alice private')||value.includes('My private connection'))),false);
    assert.deepEqual(errors,[]);
    console.log('Private Google controls, read-only flow, explicit selection, phone layout and stale-session clearing passed. No real sign-in, calendar mutation or audio.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});

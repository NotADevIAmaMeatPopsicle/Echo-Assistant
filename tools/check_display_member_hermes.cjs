/* Silent personal Hermes configuration/opt-in UI against a synthetic preview. */
const {previewBase}=require('./display_check.cjs');
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
  const base=await previewBase(),browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1024,height:600},hasTouch:true}),errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    const id='a'.repeat(32),token='synthetic-personal-key-'.repeat(3);
    const profile={mode:'guest',name:'Alex',room:'',conversation:true,home_voice:false,home_devices:{},calendars:[],cameras:[],presence_sensors:[],members:[]};
    let personal=false,saved=null,prefs={personality:'',memory_enabled:true,hermes_enabled:false};
    let config={configured:false,enabled:false,url:'',credential_saved:false,isolation_confirmed:false,revision:0};
    await page.route('**/v1/members',r=>r.fulfill({json:{items:[{id,name:'Alex',profile,revision:config.revision}]}}));
    await page.route('**/v1/members/available',r=>r.fulfill({json:{items:[{id,name:'Alex'}]}}));
    await page.route('**/v1/members/*/hermes',r=>{
      if(r.request().method()==='PUT'){
        saved=r.request().postDataJSON();config={...config,configured:!!saved.url,enabled:!!saved.enabled,url:saved.url||'',credential_saved:!!saved.url,isolation_confirmed:!!saved.isolation_confirmed,revision:config.revision+1};
      }
      return r.fulfill({json:config});
    });
    await page.route('**/v1/display/session',r=>r.fulfill({json:personal?{role:'display',profile_revision:10,profile:{...profile,personal:true},member:{id,name:'Alex',expires_at:Date.now()/1000+900}}:{role:'owner',profile_revision:0}}));
    await page.route('**/v1/member/preferences',r=>{
      if(r.request().method()==='PUT')prefs=r.request().postDataJSON();
      return r.fulfill({json:{...prefs,hermes:{configured:config.configured,enabled:config.enabled}}});
    });
    await page.route('**/v1/memory',r=>r.fulfill({json:{items:[],scope:'personal'}}));
    await page.goto(base+'/display#settings');await page.locator('#manage-members').tap();
    await page.getByRole('button',{name:'Personal agent',exact:true}).tap();
    await page.locator('#member-hermes-url').fill('https://alex-agent.example');
    await page.locator('#member-hermes-token').fill(token);await page.locator('#member-hermes-enabled').check();
    await page.locator('#member-hermes-isolated').check();await page.getByRole('button',{name:'Save connection',exact:true}).tap();
    await page.locator('#member-roster').waitFor();assert.equal(saved.token,token);assert.equal(saved.isolation_confirmed,true);
    await page.getByRole('button',{name:'Personal agent',exact:true}).tap();
    assert.equal(await page.locator('#member-hermes-token').inputValue(),'');
    assert.equal(await page.locator('#member-hermes-url').inputValue(),'https://alex-agent.example');
    assert.equal(await page.locator('#member-hermes-enabled').isChecked(),true);
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    assert.equal(await page.locator('#member-dialog').evaluate(e=>e.scrollWidth<=e.clientWidth),true);
    fs.mkdirSync('output/playwright',{recursive:true});await page.screenshot({path:'output/playwright/member-hermes-setup.png'});
    assert.equal(await page.evaluate(value=>Object.values(localStorage).some(v=>v.includes(value))||Object.values(sessionStorage).some(v=>v.includes(value)),token),false);
    personal=true;await page.reload();await page.locator('#member-button').filter({hasText:'Alex'}).tap();
    assert.equal(await page.locator('#members-card').isVisible(),false);
    assert.equal(await page.locator('#member-use-hermes').isChecked(),false);assert.equal(await page.locator('#member-use-hermes').isEnabled(),true);
    await page.locator('#member-use-hermes').check();await page.getByRole('button',{name:'Save preferences',exact:true}).tap();
    await page.locator('#member-button').filter({hasText:'Alex'}).waitFor();assert.equal(prefs.hermes_enabled,true);
    await page.locator('#member-button').tap();assert.equal(await page.locator('#member-use-hermes').isChecked(),true);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.screenshot({path:'output/playwright/member-hermes-opt-in.png'});
    assert.deepEqual(errors,[]);
    console.log('Personal Hermes owner setup, credential clearing, opt-in and narrow layout passed. No remote agent or audio used.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

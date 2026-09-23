// Run against the silent preview with playwright-cli run-code --filename <this file>.
async page=>{
  const base='http://127.0.0.1:8789';
  if(!(await (await page.request.get(base+'/health')).json()).display_demo)throw Error('A synthetic preview is required');
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{
    localStorage.setItem('echo-display-screen-v1',JSON.stringify({dim_after:0,off_after:0,hdmi_sleep:false}));
    HTMLMediaElement.prototype.play=()=>{throw Error('Playback is forbidden in this check');};
    navigator.mediaDevices.getUserMedia=()=>{throw Error('Capture is forbidden in this check');};
  });
  const check=(condition,message)=>{if(!condition)throw Error(message);};
  await page.setViewportSize({width:1024,height:600});await page.goto(base+'/display#settings');
  await page.waitForFunction(()=>data.session?.role==='owner');
  const list=page.getByRole('tablist',{name:'Settings sections'});
  check(await list.getByRole('tab').count()===7,'Settings sections missing');
  check(await page.locator('.settings-panel:visible').count()===1,'More than one section visible');
  // Every original card has a section; none is orphaned below the tabs.
  check(await page.locator('#page-settings > .card,#page-settings > .two-columns').count()===0,'Ungrouped settings card');
  const groups=await page.locator('.settings-grid').evaluateAll(grids=>grids.map(g=>({id:g.parentElement.id,cards:[...g.children].map(c=>c.querySelector('h2')?.textContent)})));
  check(groups.every(g=>g.cards.length),'Unexpected empty section');
  const tab=label=>list.getByRole('tab',{name:label,exact:true});
  await tab('Display').focus();await page.keyboard.press('ArrowRight');
  check(await tab('Voice').getAttribute('aria-selected')==='true','Arrow keys did not select Voice');
  await page.keyboard.press('End');check(await tab('System').getAttribute('aria-selected')==='true','End did not select System');
  await page.keyboard.press('Home');check(await tab('Display').getAttribute('aria-selected')==='true','Home did not select Display');
  await page.screenshot({animations:'disabled',path:'output/playwright/settings-display.png'});
  await page.evaluate(()=>document.querySelector('main').scrollTop=400);
  const sticky=await list.boundingBox();check(sticky.y>=75&&sticky.y<110,'Tab bar did not stay above scrolled content');
  await tab('Home').click();await page.locator('#google-load').click();await page.locator('#google-panel:visible').waitFor();
  await page.locator('#google-client-id').fill('synthetic-unsaved-draft');
  await tab('Voice').click();check(await page.locator('#chat-keyboard').isHidden(),'Keyboard remained over another section');
  await tab('Home').click();check(await page.locator('#google-client-id').inputValue()==='synthetic-unsaved-draft','Tab change lost a draft');
  await page.screenshot({animations:'disabled',path:'output/playwright/settings-home.png'});
  // Existing shortcuts must select their destination tab before revealing a form.
  await page.locator('#navigation [data-page=calendar]').click();await page.locator('#calendar-connect').click();
  check(await tab('Home').getAttribute('aria-selected')==='true','Calendar shortcut selected the wrong section');
  check(await page.locator('#google-calendar-card').isVisible(),'Google settings stayed hidden');
  await page.locator('#navigation [data-page=calendar]').click();await page.locator('#calendar-sources').click();
  check(await page.locator('#source-load').isVisible(),'Calendar source shortcut failed');
  await page.locator('#navigation [data-page=music]').click();await page.locator('[data-music-tab=local]').click();await page.locator('#radio-manage').click();
  check(await tab('Music').getAttribute('aria-selected')==='true','Radio shortcut selected the wrong section');
  check(await page.locator('#radio-name').isVisible(),'Radio editor stayed hidden');
  await tab('Calls & camera').click();await page.screenshot({animations:'disabled',path:'output/playwright/settings-calls.png'});
  await page.setViewportSize({width:390,height:844});await tab('System').click();
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Page overflows phone width');
  const mobileTab=await tab('System').boundingBox();check(mobileTab.x>=0&&mobileTab.x+mobileTab.width<=391,'Selected phone tab is out of view');
  check(mobileTab.height>=44,'Tab touch target is too small');
  await page.screenshot({animations:'disabled',path:'output/playwright/settings-phone.png'});
  // Role restrictions still apply after moving cards into panels.
  await page.route('**/v1/display/session',r=>r.fulfill({json:{role:'display',receiver_id:'a'.repeat(32),profile_revision:1,profile:{mode:'guest',name:'Sample guest',conversation:true}}}));
  await page.reload();await page.waitForFunction(()=>document.body.classList.contains('guest-display'));
  for(const id of ['settings-tab-access','settings-tab-system','settings-appearance','settings-overview','settings-workspace','members-card','google-calendar-card'])check(await page.locator('#'+id).isHidden(),id+' is exposed to Guest');
  check(await page.locator('.settings-panel:visible').count()===1,'Guest section fallback failed');
  check(!errors.length,errors.join('\n'));
  return {sections:groups,sticky:true,draftsPreserved:true,shortcuts:true,phone:true,guestVisibility:true,pageErrors:errors};
}

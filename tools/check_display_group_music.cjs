const {previewBase}=require('./display_check.cjs');
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
  const base=await previewBase(),browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1024,height:600}}),errors=[],changes=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/*',r=>new URL(r.request().url()).hostname==='127.0.0.1'?r.continue():r.abort());
    await page.route('**/v1/music/groups/members',r=>{changes.push(r.request().postDataJSON());return r.continue();});
    await page.goto(base+'/display#music');await page.locator('#tab-groups').click();
    const card=page.locator('[data-group-player="demo-deck"]');await card.locator('[data-group-edit]').click();
    await page.locator('#group-members-options input').check();assert.equal(changes.length,0);
    await page.locator('#group-members-cancel').click();assert.equal(changes.length,0);
    await card.locator('[data-group-edit]').click();await page.locator('#group-members-options input').check();
    fs.mkdirSync('output/playwright',{recursive:true});
    await page.screenshot({path:'output/playwright/display-group-music-rooms.png',animations:'disabled'});
    await page.locator('#group-members-save').click();await page.locator('#group-music-dialog').waitFor({state:'hidden'});
    assert.equal(changes.length,1);assert.deepEqual(changes[0].members,['demo-mini']);
    await card.getByText('Together: Echo Mini · sample').waitFor();
    await page.screenshot({path:'output/playwright/display-group-music.png',animations:'disabled'});
    await page.locator('.rail-settings').click();await page.locator('#group-music-load').click();
    assert.ok(await page.locator('#group-music-share').isDisabled());assert.equal(await page.locator('#group-music-token').inputValue(),'');
    await page.locator('#group-music-discover').click();await page.locator('#group-music-share:not(:disabled)').waitFor();
    assert.equal(await page.locator('#group-music-output-choices input:checked').count(),2);
    const guest=await browser.newPage({viewport:{width:1024,height:600}});
    await guest.route('**/v1/display/session',r=>r.fulfill({json:{role:'display',profile:{mode:'guest'},profile_revision:1}}));
    await guest.goto(base+'/display#music');await guest.locator('body.guest-display').waitFor();
    assert.equal(await guest.locator('#tab-groups').isVisible(),false);assert.equal(await guest.locator('#group-music-settings').isVisible(),false);
    await page.setViewportSize({width:390,height:844});await page.goto(base+'/display?phone-check=1#music');await page.locator('#tab-groups').click();
    await page.locator('[data-group-player="demo-deck"] [data-group-edit]').click();
    const bounds=await page.locator('#group-music-dialog').boundingBox();assert.ok(bounds.x>=0&&bounds.x+bounds.width<=390&&bounds.y+bounds.height<=844);
    await page.screenshot({path:'output/playwright/display-group-music-phone.png',animations:'disabled'});
    assert.deepEqual(errors,[]);console.log('PASS: group review/apply/cancel, selected outputs, guest restrictions and phone layout. No real audio or devices.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});

/* Synthetic-only appearance and settings navigation check. */
const {previewBase}=require('./display_check.cjs');
const {chromium}=require('playwright');
const assert=require('node:assert/strict');

(async()=>{
  const base=await previewBase(),browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const context=await browser.newContext({viewport:{width:1024,height:600}}),page=await context.newPage();
    await page.goto(base+'/display#settings');
    await page.locator('#settings-theme').waitFor();
    for(const name of ['Umbrella Grove','Mushroom Meadow','Slice Dojo']){
      assert.equal(await page.getByRole('button',{name:new RegExp(name)}).count(),1);
    }
    for(const theme of ['forest','pixel','jaunty','fruit','echo']){
      await page.locator(`[data-theme-choice="${theme}"]`).click();
      assert.equal(await page.locator('html').getAttribute('data-echo-theme'),theme);
      assert.equal(await page.locator(`[data-theme-choice="${theme}"]`).getAttribute('aria-pressed'),'true');
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    }
    await page.locator('[data-theme-choice="forest"]').click();
    await page.reload();
    assert.equal(await page.locator('html').getAttribute('data-echo-theme'),'forest');
    await page.locator('.settings-search').fill('microphone');
    await page.locator('.settings-search-result').first().click();
    assert.equal(await page.locator('#settings-tab-voice').getAttribute('aria-selected'),'true');
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    assert.equal(await page.locator('#settings-tab-system').isVisible(),true);
    console.log('PASS: five themes, local persistence, setting search, and Deck/phone bounds.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});

/* Synthetic touch navigation only; no live device or home controls. */
const {previewBase}=require('./display_check.cjs');
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
  const base=await previewBase(),browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const context=await browser.newContext({viewport:{width:1024,height:600},hasTouch:true});
    const page=await context.newPage(),errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.goto(base+'/display#home');
    await page.locator('#page-home').waitFor();
    const open=()=>page.locator('#nav-pull').getAttribute('aria-expanded');
    assert.equal(await open(),'false');
    assert.equal(await page.locator('.rail').isVisible(),false);
    assert.equal(await page.locator('.rail').getAttribute('inert'),'');
    const cdp=await context.newCDPSession(page);
    async function drag(x,y,dy){
      await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y}]});
      for(let i=1;i<=8;i++)await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x,y:y+dy*i/8}]});
      await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
    }
    await drag(510,8,150);
    assert.equal(await open(),'true');
    await page.locator('.rail').waitFor({state:'visible'});
    await page.waitForTimeout(550);
    assert.equal(await page.locator('.rail').isVisible(),true);
    fs.mkdirSync('output/playwright',{recursive:true});
    await page.screenshot({path:'output/playwright/display-navigation-deck.png',animations:'disabled'});
    await page.locator('nav [data-page=music]').tap();
    assert.equal(new URL(page.url()).hash,'#music');
    assert.equal(await open(),'false');
    await page.locator('#nav-pull').tap();
    assert.equal(await open(),'true');
    await page.waitForTimeout(300);
    await drag(510,190,-155);
    assert.equal(await open(),'false');
    await page.locator('#nav-pull').tap();
    await page.keyboard.press('Escape');
    assert.equal(await open(),'false');
    const bounds=await page.locator('.workspace').boundingBox();
    assert.equal(bounds.x,0);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.setViewportSize({width:390,height:844});
    await page.locator('#nav-pull').tap();
    assert.equal(await page.locator('.rail').isVisible(),true);
    await page.screenshot({path:'output/playwright/display-navigation-phone.png',animations:'disabled'});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.locator('#nav-close').tap();
    assert.equal(await open(),'false');
    assert.deepEqual(errors,[]);
    console.log('PASS: hidden pull-down navigation, touch open/close, page selection, keyboard close, and Deck/phone bounds.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});

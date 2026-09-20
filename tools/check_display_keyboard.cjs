/* Synthetic composer check. No live home, microphone, speech, or model calls. */
const {previewBase}=require('./display_check.cjs');
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
  const base=await previewBase(),browser=await chromium.launch({channel:'chrome',headless:true});
  try {
    const context=await browser.newContext({viewport:{width:1024,height:600},hasTouch:true});
    const page=await context.newPage(),errors=[],messages=[];
    page.on('pageerror',e=>{errors.push(e.message);console.error(e.stack);});
    await page.route('**/v1/chat',async route=>{messages.push(route.request().postDataJSON());await route.fulfill({json:{status:'complete',text:'A synthetic reply.',sources:[]}});});
    await page.goto(base+'/display#assistant');await page.locator('#send-chat:not([disabled])').waitFor();
    const input=page.locator('#chat-text'),keyboard=page.locator('#chat-keyboard');
    const dictionary=page.waitForResponse(r=>r.url().endsWith('keyboard-words.json'));
    await input.tap();
    await keyboard.waitFor({state:'visible',timeout:5000});await dictionary;
    async function tap(letter){await page.locator(`[data-key="${letter}"]`).tap();}
    async function swipe(word){
      const points=[];for(const letter of word){const b=await page.locator(`[data-letter="${letter}"]`).boundingBox();points.push([b.x+b.width/2,b.y+b.height/2]);}
      await page.mouse.move(...points[0]);await page.mouse.down();
      for(const p of points.slice(1))await page.mouse.move(...p,{steps:8});
      await page.mouse.up();
    }
    for(const l of 'hello')await tap(l);
    assert.equal(await input.inputValue(),'Hello');
    await page.locator('[data-key-action=space]').tap();await swipe('world');
    assert.equal((await input.inputValue()).trim(),'Hello world');
    assert.ok(await page.locator('#keyboard-suggestions button').count()>0);
    assert.equal(messages.length,0,'Typing/swiping must not submit');
    await page.locator('[data-key-action=backspace]').tap();assert.equal(await input.inputValue(),'Hello ');
    await swipe('echo');assert.equal((await input.inputValue()).trim(),'Hello echo');
    await page.locator('[data-key-action=mode]').tap();await tap('2');
    assert.equal(await input.inputValue(),'Hello echo 2');
    await page.locator('[data-key-action=mode]').tap();
    await input.evaluate(el=>el.setSelectionRange(0,5));await tap('h');assert.equal(await input.inputValue(),'h echo 2');
    await input.fill('');await input.tap();await swipe('weather');
    assert.equal((await input.inputValue()).trim(),'Weather');
    const alternative=page.locator('#keyboard-suggestions button').nth(1),word=await alternative.textContent();
    await alternative.tap();assert.equal((await input.inputValue()).trim(),word);
    await input.fill('');await input.tap();await swipe('weather');
    const before=await input.inputValue();
    const first=await page.locator('[data-letter=q]').boundingBox();
    const cdp=await context.newCDPSession(page);
    await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:first.x+10,y:first.y+10}]});
    await cdp.send('Input.dispatchTouchEvent',{type:'touchCancel',touchPoints:[]});
    assert.equal(await input.inputValue(),before);
    const bounds=await keyboard.boundingBox(),composer=await page.locator('#chat-form').boundingBox(),log=await page.locator('#chat-reply').boundingBox();
    assert.ok(bounds.y+bounds.height<=590&&composer.y+composer.height<=bounds.y&&log.height>=70,JSON.stringify({bounds,composer,log}));
    assert.equal(await page.locator('#voice-start').isVisible(),true);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    fs.mkdirSync('output/playwright',{recursive:true});
    await page.screenshot({path:'output/playwright/display-keyboard.png',animations:'disabled'});
    await page.locator('[data-key-action=hide]').tap();await keyboard.waitFor({state:'hidden'});
    assert.equal(await input.inputValue(),before);await page.locator('#toggle-chat-keyboard').tap();
    await page.locator('#send-chat').tap();await keyboard.waitFor({state:'hidden'});
    assert.equal(messages.length,1);assert.equal(messages[0].text,'Weather');
    await input.tap();await input.press('x');assert.equal(await keyboard.isHidden(),true);assert.equal(await input.inputValue(),'x');
    await input.tap();await page.locator('nav [data-page=home]').tap();assert.equal(await keyboard.isHidden(),true);
    await page.locator('nav [data-page=assistant]').tap();await input.tap();
    await input.fill('a'.repeat(1200));await tap('b');assert.equal((await input.inputValue()).length,1200);
    // Failed dictionary loading keeps ordinary typing available on a fresh page.
    const fallback=await context.newPage();await fallback.route('**/keyboard-words.json',r=>r.abort());
    await fallback.goto(base+'/display#assistant');await fallback.locator('#chat-text').tap();
    await fallback.getByText('Tap to type · swipe dictionary unavailable').waitFor();
    await fallback.locator('[data-key=h]').tap();assert.equal(await fallback.locator('#chat-text').inputValue(),'H');await fallback.close();
    await page.setViewportSize({width:390,height:844});await page.locator('[data-key-action=hide]').click();
    await input.tap();assert.equal(await keyboard.isHidden(),true);assert.equal(await input.getAttribute('inputmode'),'text');
    assert.deepEqual(errors,[]);
    console.log('PASS: touch typing, local glide, correction/deletion, selection, symbols, cancellation, send, physical/native keyboards, fallback and 1024x600 layout.');
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});

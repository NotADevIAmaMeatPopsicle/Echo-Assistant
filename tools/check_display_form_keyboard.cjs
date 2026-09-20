/* Touch-only form entry against synthetic data. Never uses live devices or services. */
const {previewBase}=require('./display_check.cjs');
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
  const base=await previewBase(),browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1024,height:600},hasTouch:true}),errors=[],writes=[];
    page.on('pageerror',e=>errors.push(e.message));
    page.on('request',r=>{if(r.method()==='POST'||r.method()==='PATCH')writes.push(r.url());});
    await page.goto(base+'/display#lists');
    const keyboard=page.locator('#chat-keyboard'),dock=page.locator('#display-keyboard-dock');
    async function key(value){await page.locator(`[data-key="${value}"]`).tap();}
    async function visibleField(selector){
      const field=await page.locator(selector).boundingBox(),board=await dock.boundingBox();
      assert.ok(field.y>=0&&field.y+field.height<=board.y+1,JSON.stringify({selector,field,board}));
      assert.ok(board.x>=0&&board.x+board.width<=1024&&board.y+board.height<=600);
    }
    await page.locator('#list-text:not(:disabled)').tap();await keyboard.waitFor({state:'visible'});
    for(const letter of 'milk')await key(letter);
    assert.equal(await page.locator('#list-text').inputValue(),'Milk');assert.equal(writes.length,0);
    await visibleField('#list-text');
    fs.mkdirSync('output/playwright',{recursive:true});
    await page.screenshot({path:'output/playwright/display-list-keyboard.png',animations:'disabled'});
    await page.locator('#list-form button[type=submit]').tap();
    await page.locator('#household-items .item-text').getByText('Milk',{exact:true}).waitFor();
    assert.equal(writes.length,1);await keyboard.waitFor({state:'hidden'});
    const milk=page.locator('.household-item').filter({hasText:'Milk'});
    await milk.locator('[data-edit-item]').tap();await page.locator('#list-edit-text').tap();
    await keyboard.waitFor({state:'visible'});
    assert.equal(await dock.evaluate(el=>el.parentElement.matches('dialog[open]')),true);
    await page.locator('#list-edit-text').evaluate(el=>el.setSelectionRange(el.value.length,el.value.length));
    await page.locator('[data-key-action=finish]').tap();for(const l of 'oat')await key(l);
    assert.equal(await page.locator('#list-edit-text').inputValue(),'Milk\noat');assert.equal(writes.length,1);
    await visibleField('#list-edit-text');
    await page.screenshot({path:'output/playwright/display-note-keyboard.png',animations:'disabled'});
    await page.locator('#list-edit-cancel').tap();await keyboard.waitFor({state:'hidden'});assert.equal(writes.length,1);
    await page.locator('nav [data-page=day]').tap();await page.locator('#calendar-create').tap();
    await page.locator('#event-title').tap();await keyboard.waitFor({state:'visible'});
    for(const l of 'lunch')await key(l);
    assert.equal(await page.locator('#event-title').inputValue(),'Lunch');await visibleField('#event-title');
    await page.screenshot({path:'output/playwright/display-calendar-keyboard.png',animations:'disabled'});
    await page.locator('[data-key-action=next]').tap();
    assert.equal(await page.evaluate(()=>document.activeElement.id),'event-timezone');
    await page.locator('[data-key-action=previous]').tap();
    assert.equal(await page.evaluate(()=>document.activeElement.id),'event-title');
    await page.locator('#event-start').tap();await keyboard.waitFor({state:'hidden'});
    await page.locator('#event-title').tap();await keyboard.waitFor({state:'visible'});
    await page.locator('#calendar-event-fields').evaluate(el=>el.disabled=true);await keyboard.waitFor({state:'hidden'});
    await page.locator('#calendar-event-cancel').tap();assert.equal(writes.length,1,'Draft entry never creates an event');
    // A limitless field and private/literal field exercise the shared entry contract.
    await page.locator('nav [data-page=lists]').tap();
    await page.evaluate(()=>{
      const form=document.createElement('form');form.id='keyboard-fixture';
      form.innerHTML='<label>Local text<input id="limitless"></label><label>Private text<input id="private-text" type="password" inputmode="text"></label><label>Numeric control<input id="native-number" type="number"></label>';
      document.getElementById('page-lists').prepend(form);
    });
    await page.locator('#limitless').tap();await key('a');assert.equal(await page.locator('#limitless').inputValue(),'A');
    await page.locator('[data-key-action=next]').tap();await key('a');
    assert.equal(await page.locator('#private-text').inputValue(),'a');assert.equal(await page.locator('#keyboard-suggestions button').count(),0);
    await page.locator('[data-key-action=mode]').tap();await key('_');await key('-');
    assert.equal(await page.locator('#private-text').inputValue(),'a_-');
    await page.locator('[data-key-action=finish]').tap();await keyboard.waitFor({state:'hidden'});
    assert.equal(await page.locator('#private-text').getAttribute('inputmode'),'text');
    assert.equal(await page.locator('#limitless').getAttribute('inputmode'),null);
    await page.locator('#native-number').tap();assert.equal(await keyboard.isHidden(),true);
    await page.locator('#limitless').tap();await page.setViewportSize({width:390,height:844});await keyboard.waitFor({state:'hidden'});
    await page.locator('#limitless').tap();assert.equal(await keyboard.isHidden(),true);
    assert.deepEqual(errors,[]);console.log('PASS: touch-only list/form/modal editing, explicit saves, caret/newline, field navigation, limits, private entry and native controls.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

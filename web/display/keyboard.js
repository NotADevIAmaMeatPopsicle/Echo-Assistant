/* Local touchscreen text entry. No key logging, storage, or remote inference. */
(()=>{
  'use strict';
  const chatInput=document.getElementById('chat-text'),panel=document.getElementById('chat-keyboard');
  let input=chatInput,originalMode=null,modeOwned=false,keyboardDialog=null;
  const home=document.createComment('Echo keyboard home');panel.before(home);
  const dock=document.createElement('div');dock.id='display-keyboard-dock';dock.hidden=true;document.body.append(dock);
  const keys=document.getElementById('keyboard-keys'),toggle=document.getElementById('toggle-chat-keyboard');
  const suggestions=document.getElementById('keyboard-suggestions'),status=document.getElementById('keyboard-status');
  const trail=document.getElementById('keyboard-trail'),line=trail.querySelector('polyline');
  const lexicon=new EchoSwipeLexicon();
  let shifted=false,symbols=false,gesture=null,replacement=null,changing=false,focusTimer=null;
  const fieldBar=document.createElement('div');fieldBar.className='keyboard-field-bar';fieldBar.hidden=true;
  fieldBar.innerHTML='<span id="keyboard-field-name"></span><button type="button" data-key-action="previous" aria-label="Previous text field">‹</button><button type="button" data-key-action="next" aria-label="Next text field">›</button>';
  panel.prepend(fieldBar);
  function eligible(target){
    return (target instanceof HTMLTextAreaElement||target instanceof HTMLInputElement&&['text','search','url','tel','password'].includes(target.type))
      &&!target.matches(':disabled')&&!target.readOnly&&!target.closest('[hidden],[inert]')&&target.getClientRects().length>0;
  }
  const wordsAllowed=()=>!['password','url','tel'].includes(input.type)&&input.dataset.keyboard!=='literal'&&input.autocomplete!=='one-time-code';
  function fields(){return [...(input.form||input.closest('.page')||document).querySelectorAll('input,textarea')].filter(eligible);}
  function fieldControls(){
    const list=fields(),index=list.indexOf(input);
    fieldBar.querySelector('[data-key-action=previous]').disabled=index<=0;
    fieldBar.querySelector('[data-key-action=next]').disabled=index<0||index>=list.length-1;
    document.getElementById('keyboard-field-name').textContent=(input.labels?.[0]?.textContent||input.getAttribute('aria-label')||input.placeholder||'Text').trim().replace(/\s+/g,' ').slice(0,60);
  }
  const selection=()=>[input.selectionStart??input.value.length,input.selectionEnd??input.value.length];
  function capitalize(word) {return shifted?word[0].toUpperCase()+word.slice(1):word;}
  function sentenceCase() { shifted=wordsAllowed()&&/(?:^|[.!?]\s+)$/.test(input.value.slice(0,selection()[0])); }
  function hint(text=wordsAllowed()?'Tap or swipe a word · English':'Tap to type · suggestions off') {
    const node=document.createElement('span');node.className='keyboard-hint';node.textContent=text;suggestions.replaceChildren(node);
  }
  function edit(text,start=selection()[0],end=selection()[1]) {
    if(!eligible(input)){close();return false;}
    const length=input.value.length-(end-start)+text.length;
    if(input.maxLength>=0&&length>input.maxLength){status.textContent='Character limit reached.';return false;}
    input.setRangeText(text,start,end,'end');changing=true;input.dispatchEvent(new Event('input',{bubbles:true}));changing=false;
    input.focus({preventScroll:true});return true;
  }
  function candidates(words,start,end) {
    suggestions.replaceChildren();
    words.forEach(word=>{
      const button=document.createElement('button');button.type='button';button.textContent=word;
      button.addEventListener('click',()=>{
        if(edit(word+' ',start,end)){replacement={start,end:start+word.length+1,text:word+' '};sentenceCase();render();hint();}
      });
      suggestions.append(button);
    });
  }
  function completions() {
    if(!wordsAllowed()){replacement=null;hint();return;}
    replacement=null;const [start,end]=selection();
    const prefix=start===end?input.value.slice(0,start).match(/[a-z]+$/i)?.[0]:null;
    const words=prefix?lexicon.complete(prefix):[];
    if(words.length)candidates(words.map(w=>/^[A-Z]/.test(prefix)?w[0].toUpperCase()+w.slice(1):w),start-prefix.length,end);
    else hint();
  }
  function key(label,action,value) {
    const button=document.createElement('button');button.type='button';button.className='keyboard-key';button.textContent=label;
    if(action){button.dataset.keyAction=action;button.setAttribute('aria-label',({shift:'Shift',backspace:'Backspace',mode:symbols?'Letters':'Numbers and symbols',space:'Space',left:'Move caret left',right:'Move caret right',finish:input instanceof HTMLTextAreaElement?'New line':'Done typing'})[action]);}
    else {button.dataset.key=value;button.setAttribute('aria-label',label);if(/^[a-z]$/.test(value))button.dataset.letter=value;}
    if(action==='shift')button.setAttribute('aria-pressed',String(shifted));
    return button;
  }
  function render() {
    keys.querySelectorAll('.keyboard-row').forEach(row=>row.remove());
    const rows=symbols?['1234567890','@#$%&*+=/','!?():;"-_']:['qwertyuiop','asdfghjkl','zxcvbnm'];
    rows.forEach((letters,index)=>{
      const row=document.createElement('div');row.className='keyboard-row';row.dataset.row=index;
      if(index===2)row.append(symbols?key("'",null,"'"):key('⇧','shift'));
      for(const letter of letters)row.append(key(!symbols&&shifted?letter.toUpperCase():letter,null,letter));
      if(index===2)row.append(key('⌫','backspace'));
      keys.append(row);
    });
    const row=document.createElement('div');row.className='keyboard-row';
    row.append(key(symbols?'ABC':'123','mode'),key(',',null,','),key('space','space'),key('.',null,'.'),key('‹','left'),key('›','right'));
    if(input!==chatInput)row.append(key(input instanceof HTMLTextAreaElement?'↵':'Done','finish'));
    keys.append(row);
  }
  function cancelGesture() {
    const previous=gesture;gesture=null;
    if(previous&&keys.hasPointerCapture(previous.id))keys.releasePointerCapture(previous.id);
    line.setAttribute('points','');keys.querySelectorAll('.is-traced').forEach(key=>key.classList.remove('is-traced'));
  }
  function restoreMode(){
    if(!modeOwned)return;
    if(originalMode===null)input.removeAttribute('inputmode');else input.setAttribute('inputmode',originalMode);
    modeOwned=false;
  }
  function keepVisible(){
    if(panel.hidden||!eligible(input))return;
    const height=Math.ceil(dock.getBoundingClientRect().height);
    document.body.style.setProperty('--echo-keyboard-height',height+'px');
    if(keyboardDialog)keyboardDialog.style.setProperty('--echo-keyboard-height',height+'px');
    if(input!==chatInput)input.scrollIntoView({block:'nearest',inline:'nearest',behavior:'instant'});
  }
  function open(target=input) {
    clearTimeout(focusTimer);focusTimer=null;
    if(!eligible(target))return;
    if(!panel.hidden&&target===input){fieldControls();return;}
    cancelGesture();restoreMode();keyboardDialog?.classList.remove('with-echo-keyboard');keyboardDialog?.style.removeProperty('--echo-keyboard-height');
    input=target;replacement=null;symbols=false;status.textContent='';
    originalMode=input.getAttribute('inputmode');modeOwned=true;
    keyboardDialog=input.closest('dialog[open]');
    const chat=input===chatInput;
    document.body.classList.toggle('chat-keyboard-open',chat);
    document.body.classList.toggle('form-keyboard-open',!chat&&!keyboardDialog);
    fieldBar.hidden=chat;fieldControls();
    if(chat){home.after(panel);dock.hidden=true;}
    else{(keyboardDialog||document.body).append(dock);dock.append(panel);dock.hidden=false;}
    dock.classList.toggle('inside-dialog',!!keyboardDialog);keyboardDialog?.classList.add('with-echo-keyboard');
    panel.hidden=false;toggle.setAttribute('aria-expanded',String(chat));toggle.setAttribute('aria-label',chat?'Hide keyboard':'Show keyboard');
    input.inputMode='none';sentenceCase();render();hint();
    requestAnimationFrame(keepVisible);
    if(wordsAllowed())lexicon.load().then(()=>{if(!panel.hidden&&!gesture)completions();}).catch(()=>{if(!panel.hidden&&wordsAllowed())hint('Tap to type · swipe dictionary unavailable');});
  }
  function close() {
    clearTimeout(focusTimer);focusTimer=null;
    cancelGesture();restoreMode();panel.hidden=true;dock.hidden=true;home.after(panel);
    keyboardDialog?.classList.remove('with-echo-keyboard');keyboardDialog?.style.removeProperty('--echo-keyboard-height');keyboardDialog=null;
    document.body.classList.remove('chat-keyboard-open','form-keyboard-open');toggle.setAttribute('aria-expanded','false');toggle.setAttribute('aria-label','Show keyboard');
    document.body.style.removeProperty('--echo-keyboard-height');replacement=null;hint();status.textContent='';
  }
  function press(button) {
    const action=button.dataset.keyAction,[start,end]=selection();
    if(action==='hide'){close();return;}
    if(action==='previous'||action==='next'){
      const list=fields(),next=list[list.indexOf(input)+(action==='next'?1:-1)];
      if(next){next.focus({preventScroll:true});open(next);}return;
    }
    if(action==='finish'){
      if(input instanceof HTMLTextAreaElement){edit('\n');sentenceCase();render();completions();}
      else{close();input.blur();}return;
    }
    if(action==='shift'){shifted=!shifted;render();return;}
    if(action==='mode'){symbols=!symbols;render();return;}
    if(action==='left'||action==='right'){
      const step=action==='left'?-1:1,pos=Math.max(0,Math.min(input.value.length,(step<0?start:end)+step));
      input.setSelectionRange(pos,pos);replacement=null;sentenceCase();render();completions();return;
    }
    if(action==='backspace'){
      if(start!==end)edit('',start,end);
      else if(replacement&&start===replacement.end&&input.value.slice(replacement.start,replacement.end)===replacement.text)edit('',replacement.start,replacement.end);
      else if(start){const last=[...input.value.slice(0,start)].at(-1);edit('',start-last.length,start);}
      replacement=null;sentenceCase();render();completions();return;
    }
    const text=action==='space'?' ':!symbols?capitalize(button.dataset.key):button.dataset.key;
    if(text&&edit(text)){sentenceCase();render();completions();}
  }
  panel.addEventListener('pointerdown',event=>{
    if(event.target.closest('button'))event.preventDefault(); // Keep the input's caret and selection.
  });
  panel.addEventListener('click',event=>{
    const button=event.target.closest('.keyboard-key,[data-key-action]');
    if(button&&!button.dataset.letter)press(button);
    else if(button&&event.detail===0)press(button); // Keyboard/assistive activation.
  });
  keys.addEventListener('pointerdown',event=>{
    const button=event.target.closest('[data-letter]');
    if(!button||!event.isPrimary||event.button!==0||gesture)return;
    const boxes=[...keys.querySelectorAll('[data-letter]')].map(b=>({button:b,letter:b.dataset.letter,box:b.getBoundingClientRect()}));
    const first=boxes.find(b=>b.letter==='q').box,second=boxes.find(b=>b.letter==='w').box,lower=boxes.find(b=>b.letter==='a').box;
    gesture={id:event.pointerId,button,boxes,target:input,start:selection(),value:input.value,shifted,points:[],distance:0,
      origin:[first.x+first.width/2,first.y+first.height/2],step:[second.x-first.x,lower.y-first.y]};
    keys.setPointerCapture(event.pointerId);sample(event);
  });
  function sample(event) {
    if(!gesture||event.pointerId!==gesture.id)return;
    const p=[(event.clientX-gesture.origin[0])/gesture.step[0],(event.clientY-gesture.origin[1])/gesture.step[1]],last=gesture.points.at(-1);
    if(last){const d=Math.hypot(p[0]-last[0],p[1]-last[1]);if(d<.05)return;gesture.distance+=d;}
    if(gesture.points.length>=512)return;
    gesture.points.push(p);
    const rect=keys.getBoundingClientRect();
    if(gesture.distance>.5)line.setAttribute('points',gesture.points.map(v=>[v[0]*gesture.step[0]+gesture.origin[0]-rect.x,v[1]*gesture.step[1]+gesture.origin[1]-rect.y].join(',')).join(' '));
    for(const item of gesture.boxes)item.button.classList.toggle('is-traced',event.clientX>=item.box.left&&event.clientX<=item.box.right&&event.clientY>=item.box.top&&event.clientY<=item.box.bottom);
  }
  keys.addEventListener('pointermove',sample);
  keys.addEventListener('pointerup',event=>{
    if(!gesture||event.pointerId!==gesture.id)return;
    sample(event);const g=gesture;cancelGesture();
    if(g.target!==input||g.value!==input.value||!eligible(input))return;
    if(g.distance<.7){press(g.button);return;}
    if(!wordsAllowed()){hint();return;}
    const words=lexicon.decode(g.points).map(word=>g.shifted?word[0].toUpperCase()+word.slice(1):word);
    if(!words.length){hint(lexicon.words.length?'Try that word again, or tap its letters.':'Tap to type while swipe loads.');return;}
    const before=input.value.slice(0,g.start[0]),prefix=/[a-z0-9]$/i.test(before)?' ':'';
    const text=prefix+words[0]+' ';
    if(edit(text,...g.start)){
      replacement={start:g.start[0],end:g.start[0]+text.length,text};
      candidates(words,g.start[0]+prefix.length,replacement.end);status.textContent=words[0]+'. Alternatives above the keyboard.';sentenceCase();render();
    }
  });
  keys.addEventListener('pointercancel',cancelGesture);
  keys.addEventListener('lostpointercapture',()=>{if(gesture)cancelGesture();});
  // Defer focus reflow until the opening tap has finished targeting the input.
  document.addEventListener('focusin',event=>{
    const target=event.target;if(panel.contains(target))return;
    clearTimeout(focusTimer);focusTimer=null;
    if(innerWidth>760&&eligible(target))focusTimer=setTimeout(()=>{if(document.activeElement===target)open(target);},0);
    // Other controls finish their click before closing. Reflow on focus can
    // move checkboxes, pickers and Send/Save out from under the opening tap.
  });
  document.addEventListener('input',event=>{if(event.target===input&&!changing){replacement=null;if(!panel.hidden)completions();}});
  document.addEventListener('keydown',event=>{if(event.key==='Tab'||event.target===input&&(event.key==='Escape'||event.key.length===1||event.key==='Backspace'||event.key==='Enter'))close();});
  toggle.addEventListener('pointerdown',event=>event.preventDefault());
  toggle.addEventListener('click',()=>{if(panel.hidden||input!==chatInput){chatInput.focus({preventScroll:true});open(chatInput);}else close();});
  document.getElementById('voice-start').addEventListener('click',close);
  document.addEventListener('submit',event=>{if(input.form===event.target)close();});
  document.addEventListener('echo:page',close);
  document.addEventListener('close',event=>{if(event.target===keyboardDialog)close();},true);
  document.addEventListener('visibilitychange',()=>{if(document.hidden)close();});
  document.addEventListener('click',event=>{
    const path=event.composedPath();
    if(path.includes(panel)||path.includes(toggle))return;
    if(eligible(event.target)&&innerWidth>760){open(event.target);if(!replacement){sentenceCase();render();completions();}return;}
    if(!panel.hidden&&!path.includes(input.closest('.chat-composer')))close();
  });
  new MutationObserver(()=>{if(!panel.hidden&&!eligible(input))close();}).observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['disabled','hidden','inert','open']});
  window.addEventListener('resize',()=>{cancelGesture();if(innerWidth<=760&&input!==chatInput)close();else requestAnimationFrame(keepVisible);});
})();

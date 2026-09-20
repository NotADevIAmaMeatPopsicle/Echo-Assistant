/* Scoped to Echo's composer. No key logging, storage, or remote inference. */
(()=>{
  'use strict';
  const input=document.getElementById('chat-text'),panel=document.getElementById('chat-keyboard');
  const keys=document.getElementById('keyboard-keys'),toggle=document.getElementById('toggle-chat-keyboard');
  const suggestions=document.getElementById('keyboard-suggestions'),status=document.getElementById('keyboard-status');
  const trail=document.getElementById('keyboard-trail'),line=trail.querySelector('polyline');
  const lexicon=new EchoSwipeLexicon();
  let shifted=false,symbols=false,gesture=null,replacement=null,changing=false,focusTimer=null;
  const selection=()=>[input.selectionStart??input.value.length,input.selectionEnd??input.value.length];
  function capitalize(word) {return shifted?word[0].toUpperCase()+word.slice(1):word;}
  function sentenceCase() { shifted=/(?:^|[.!?]\s+)$/.test(input.value.slice(0,selection()[0])); }
  function hint(text='Tap or swipe a word · English') {
    const node=document.createElement('span');node.className='keyboard-hint';node.textContent=text;suggestions.replaceChildren(node);
  }
  function edit(text,start=selection()[0],end=selection()[1]) {
    const length=input.value.length-(end-start)+text.length;
    if(length>input.maxLength){status.textContent='Message limit reached.';return false;}
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
    replacement=null;const [start,end]=selection();
    const prefix=start===end?input.value.slice(0,start).match(/[a-z]+$/i)?.[0]:null;
    const words=prefix?lexicon.complete(prefix):[];
    if(words.length)candidates(words.map(w=>/^[A-Z]/.test(prefix)?w[0].toUpperCase()+w.slice(1):w),start-prefix.length,end);
    else hint();
  }
  function key(label,action,value) {
    const button=document.createElement('button');button.type='button';button.className='keyboard-key';button.textContent=label;
    if(action){button.dataset.keyAction=action;button.setAttribute('aria-label',({shift:'Shift',backspace:'Backspace',mode:symbols?'Letters':'Numbers and symbols',space:'Space',left:'Move caret left',right:'Move caret right'})[action]);}
    else {button.dataset.key=value;button.setAttribute('aria-label',label);if(/^[a-z]$/.test(value))button.dataset.letter=value;}
    if(action==='shift')button.setAttribute('aria-pressed',String(shifted));
    return button;
  }
  function render() {
    keys.querySelectorAll('.keyboard-row').forEach(row=>row.remove());
    const rows=symbols?['1234567890','@#$%&*+=/','!?():;"']:['qwertyuiop','asdfghjkl','zxcvbnm'];
    rows.forEach((letters,index)=>{
      const row=document.createElement('div');row.className='keyboard-row';row.dataset.row=index;
      if(index===2)row.append(symbols?key("'",null,"'"):key('⇧','shift'));
      for(const letter of letters)row.append(key(!symbols&&shifted?letter.toUpperCase():letter,null,letter));
      if(index===2)row.append(key('⌫','backspace'));
      keys.append(row);
    });
    const row=document.createElement('div');row.className='keyboard-row';
    row.append(key(symbols?'ABC':'123','mode'),key(',',null,','),key('space','space'),key('.',null,'.'),key('‹','left'),key('›','right'));
    keys.append(row);
  }
  function cancelGesture() {
    const previous=gesture;gesture=null;
    if(previous&&keys.hasPointerCapture(previous.id))keys.releasePointerCapture(previous.id);
    line.setAttribute('points','');keys.querySelectorAll('.is-traced').forEach(key=>key.classList.remove('is-traced'));
  }
  function open() {
    clearTimeout(focusTimer);focusTimer=null;
    if(!panel.hidden)return;
    panel.hidden=false;document.body.classList.add('chat-keyboard-open');toggle.setAttribute('aria-expanded','true');toggle.setAttribute('aria-label','Hide keyboard');
    input.inputMode='none';sentenceCase();render();hint();
    lexicon.load().then(()=>{if(!panel.hidden&&!gesture)completions();}).catch(()=>{if(!panel.hidden)hint('Tap to type · swipe dictionary unavailable');});
  }
  function close() {
    clearTimeout(focusTimer);focusTimer=null;
    cancelGesture();panel.hidden=true;document.body.classList.remove('chat-keyboard-open');toggle.setAttribute('aria-expanded','false');toggle.setAttribute('aria-label','Show keyboard');
    input.inputMode='text';replacement=null;hint();
  }
  function press(button) {
    const action=button.dataset.keyAction,[start,end]=selection();
    if(action==='hide'){close();return;}
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
    const button=event.target.closest('.keyboard-key,[data-key-action=hide]');
    if(button&&!button.dataset.letter)press(button);
    else if(button&&event.detail===0)press(button); // Keyboard/assistive activation.
  });
  keys.addEventListener('pointerdown',event=>{
    const button=event.target.closest('[data-letter]');
    if(!button||!event.isPrimary||event.button!==0||gesture)return;
    const boxes=[...keys.querySelectorAll('[data-letter]')].map(b=>({button:b,letter:b.dataset.letter,box:b.getBoundingClientRect()}));
    const first=boxes.find(b=>b.letter==='q').box,second=boxes.find(b=>b.letter==='w').box,lower=boxes.find(b=>b.letter==='a').box;
    gesture={id:event.pointerId,button,boxes,start:selection(),value:input.value,shifted,points:[],distance:0,
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
    if(g.value!==input.value)return;
    if(g.distance<.7){press(g.button);return;}
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
  input.addEventListener('focus',()=>{if(innerWidth>760)focusTimer=setTimeout(()=>{if(document.activeElement===input)open();},0);});
  input.addEventListener('click',()=>{if(innerWidth>760)open();if(!panel.hidden&&!replacement){sentenceCase();render();completions();}});
  input.addEventListener('input',()=>{if(!changing){replacement=null;if(!panel.hidden)completions();}});
  input.addEventListener('keydown',event=>{if(event.key==='Escape'||event.key.length===1||event.key==='Backspace'||event.key==='Enter')close();});
  toggle.addEventListener('pointerdown',event=>event.preventDefault());
  toggle.addEventListener('click',()=>{if(panel.hidden){open();input.focus({preventScroll:true});}else close();});
  document.getElementById('voice-start').addEventListener('click',close);
  document.getElementById('chat-form').addEventListener('submit',()=>{if(!input.value)close();});
  document.addEventListener('echo:page',event=>{if(event.detail!=='assistant')close();});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)close();});
  document.addEventListener('click',event=>{
    const path=event.composedPath();
    if(!panel.hidden&&!path.includes(panel)&&!path.includes(input.closest('.chat-composer')))close();
  });
  window.addEventListener('resize',cancelGesture);
})();

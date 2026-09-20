/* Idle display protection. No camera, microphone sampling, or occupancy tracking. */
(() => {
  'use strict';
  const defaults={dim_after:120,off_after:600,hdmi_sleep:false},times=[0,60,120,300,600,900,1800,3600],key='echo-display-screen-v1';
  let settings={...defaults},native=false,mode='awake',lastActivity=Date.now(),lastPulse=0,blockedPointer=false,blockClick=false,priorFocus=null,manualSleep=false;
  const valid=v=>v&&times.includes(v.dim_after)&&times.includes(v.off_after)&&typeof v.hdmi_sleep==='boolean'&&(!v.off_after||v.dim_after<v.off_after);
  try{const saved=JSON.parse(localStorage.getItem(key));if(valid(saved))settings=saved;}catch{}
  const presenceKey='echo-display-presence-v1';
  let presenceSensor='',presenceItems=[],presenceBusy=false,presenceAt=0,presenceOccupied=false,presenceSuppressed=false,presenceSelectionReady=false;
  try{const saved=localStorage.getItem(presenceKey);if(/^binary_sensor\.[a-z0-9_]{1,128}$/.test(saved))presenceSensor=saved;}catch{}
  const cover=document.createElement('button');cover.id='screen-cover';cover.type='button';cover.tabIndex=-1;cover.setAttribute('aria-label','Wake display');cover.dataset.mode='awake';cover.hidden=true;document.body.append(cover);
  const card=document.createElement('article');card.id='screen-settings';card.className='card';
  const options=times.map(s=>`<option value="${s}">${s?s<3600?s/60+' minutes':'1 hour':'Never'}</option>`).join('');
  card.innerHTML=`<span class="eyebrow">SCREEN COMFORT</span><h2>A little rest for your display.</h2><form id="screen-form"><label>Dim after<select id="screen-dim">${options}</select></label><label>Sleep after<select id="screen-off">${options}</select></label><label class="check-label screen-wide" id="screen-hdmi-label" hidden><input id="screen-hdmi" type="checkbox">Switch off the display signal when sleeping</label><p class="tiny soft screen-wide" id="screen-power-note">Dimming shades the screen; sleep makes it black. Hardware backlight control depends on your display.</p><p class="tiny soft screen-wide">Tap once to wake, then tap a control to use it. Music and voice stay available. A recognized wake word also wakes the screen. Presence wake needs a connected sensor; none is configured.</p><div class="row screen-wide"><button type="submit" class="pill primary">Save screen settings</button><button type="button" class="pill" id="screen-sleep-now">Sleep now</button></div><p class="tiny soft screen-wide" id="screen-message" role="status"></p></form>`;
  $('page-settings').firstElementChild.after(card);
  const presenceLabel=document.createElement('label');presenceLabel.className='screen-wide';
  presenceLabel.innerHTML='Wake with presence<select id="screen-presence"><option value="">Off · touch or wake word only</option></select>';
  $('screen-power-note').after(presenceLabel);
  const presenceNote=document.createElement('p');presenceNote.id='screen-presence-note';presenceNote.className='tiny soft screen-wide';presenceNote.setAttribute('role','status');presenceLabel.after(presenceNote);
  $('screen-power-note').parentElement.querySelectorAll('p').forEach(p=>{if(p.textContent.includes('Presence wake needs'))p.textContent='Tap once to wake, then tap a control to use it. Music and voice stay available. A recognized wake word also wakes the screen.';});
  function presenceOptions(){
    const select=$('screen-presence'),draft=presenceSelectionReady?select.value:presenceSensor;
    if(document.activeElement===select)return;
    const items=[...presenceItems];if(draft&&!items.some(i=>i.entity_id===draft))items.push({entity_id:draft,name:'Saved sensor · not shared or unavailable',available:false});
    // Text nodes keep names from home integrations out of HTML.
    select.replaceChildren(new Option('Off · touch or wake word only',''),...items.map(i=>new Option(i.name+(i.available?'':' · unavailable'),i.entity_id)));
    select.value=draft;presenceSelectionReady=true;
  }
  async function pollPresence(){
    if(presenceBusy)return;
    presenceBusy=true;const selected=presenceSensor;
    try{
      const response=await fetch('/v1/display/presence',{cache:'no-store',signal:AbortSignal.timeout(4000)});
      if(!response.ok)throw new Error();
      const value=await response.json();if(!Array.isArray(value.items))throw new Error();
      presenceItems=value.items;presenceOptions();
      if(selected!==presenceSensor)return;
      const sensor=presenceItems.find(i=>i.entity_id===selected);
      presenceAt=Date.now();presenceOccupied=sensor?.available===true&&sensor.occupied===true;
      if(sensor?.available===true&&sensor.occupied===false)presenceSuppressed=false;
      presenceNote.textContent=!selected?(presenceItems.length?'Choose a shared sensor in the same room. This choice applies only to this display.':'No sensors shared. In the owner workspace, open Settings → Calendars & cameras → Load sources to share a motion or occupancy sensor.'):
        !sensor?.available?'Selected sensor unavailable or no longer shared. Touch and wake words still work.':presenceSuppressed?'Sleeping until this sensor clears and detects someone again.':presenceOccupied?'Presence detected · keeping this display awake.':'Ready to wake when presence is detected.';
      if(presenceOccupied&&!presenceSuppressed)wake();
    }catch{presenceAt=0;presenceOccupied=false;presenceNote.textContent='Presence connection unavailable. Touch and wake words still work.';}
    finally{presenceBusy=false;}
  }
  async function request(method='GET',value){
    const r=await fetch('/v1/display/screen',{method,headers:method==='GET'?{}:{'Content-Type':'application/json','X-Echo-Request':'1'},body:value?JSON.stringify(value):undefined,signal:AbortSignal.timeout(5000)});
    if(!r.ok)throw new Error('Screen settings could not reach this Pi.');return r.json();
  }
  function fill(){ $('screen-dim').value=settings.dim_after;$('screen-off').value=settings.off_after;$('screen-hdmi').checked=settings.hdmi_sleep; }
  function pulse(){if(native&&Date.now()-lastPulse>4000){lastPulse=Date.now();request('POST',{action:'wake'}).catch(()=>{});}}
  function display(next){
    if(mode===next)return;
    if(next==='sleep'){
      priorFocus=document.activeElement;
      if(!$('ambient').hidden)ambient(false);
      document.querySelectorAll('.rail,.workspace').forEach(n=>n.inert=true);
    }else if(mode==='sleep'){
      document.querySelectorAll('.rail,.workspace').forEach(n=>n.inert=false);
    }
    mode=next;cover.dataset.mode=mode;cover.hidden=mode==='awake';document.body.classList.toggle('screen-sleeping',mode==='sleep');
    if(mode==='sleep')cover.focus({preventScroll:true});
    else if(mode==='awake'&&priorFocus){priorFocus.focus({preventScroll:true});priorFocus=null;}
  }
  function wake(){manualSleep=false;presenceSuppressed=false;lastActivity=Date.now();lastInput=lastActivity;display('awake');pulse();}
  function consume(event){event.preventDefault();event.stopImmediatePropagation();}
  // Capture before page controls, glide typing, and swipe navigation. A wake tap
  // cannot also toggle a light or send a message when the display comes back.
  window.addEventListener('pointerdown',event=>{
    if(mode==='sleep'){blockedPointer=true;blockClick=true;consume(event);wake();}
    else{blockedPointer=false;blockClick=false;wake();}
  },true);
  for(const type of ['pointermove','pointerup','pointercancel'])window.addEventListener(type,event=>{
    if(blockedPointer){consume(event);if(type!=='pointermove')blockedPointer=false;}
  },true);
  window.addEventListener('click',event=>{if(blockClick){blockClick=false;consume(event);}},true);
  window.addEventListener('keydown',event=>{if(mode==='sleep'){consume(event);blockClick=true;}wake();},true);
  window.addEventListener('wheel',()=>{if(mode!=='sleep')wake();},{passive:true});
  function engaged(){
    return !!chatAbort||displayCaptureBusy||busy||(typeof piVoiceBusy==='function'&&fresh('piVoice')&&piVoiceBusy())||
      !!document.querySelector('dialog[open]')||[...document.querySelectorAll('video')].some(v=>!v.paused&&!v.ended);
  }
  function tickScreen(){
    if(engaged()||(presenceOccupied&&!presenceSuppressed&&Date.now()-presenceAt<12000)){wake();return;}
    const seconds=(Date.now()-lastActivity)/1000;
    display(settings.off_after&&seconds>=settings.off_after?'sleep':settings.dim_after&&seconds>=settings.dim_after?'dim':'awake');
  }
  $('screen-form').onsubmit=async event=>{
    event.preventDefault();const next={dim_after:Number($('screen-dim').value),off_after:Number($('screen-off').value),hdmi_sleep:native&&$('screen-hdmi').checked};
    if(!valid(next)){$('screen-message').textContent='Choose a sleep time later than dimming, or set dimming to Never.';return;}
    const submit=event.submitter;if(submit)submit.disabled=true;
    try{
      if(native)await request('PUT',next);
      settings=next;
      presenceSensor=$('screen-presence').value;presenceAt=0;presenceOccupied=false;
      try{localStorage.setItem(key,JSON.stringify(settings));$('screen-message').textContent='Screen settings saved.';}
      catch{$('screen-message').textContent=native?'Saved on this Pi.':'Settings apply for this tab only.';}
      try{localStorage.setItem(presenceKey,presenceSensor);}catch{$('screen-message').textContent+=' Presence choice applies for this tab only.';}
      wake();pollPresence();
    }catch(error){$('screen-message').textContent=error.message;}
    finally{if(submit)submit.disabled=false;}
  };
  $('screen-sleep-now').onclick=()=>{
    lastActivity=Date.now()-(settings.off_after||600)*1000;
    display('sleep');
    // Sleep now stays asleep even if the automatic sleep timer is disabled.
    manualSleep=true;
    presenceSuppressed=true;
    if(native&&settings.hdmi_sleep&&settings.off_after)request('POST',{action:'sleep'}).catch(()=>{$('screen-message').textContent='HDMI sleep unavailable; the screen is black.';});
  };
  fill();
  presenceOptions();pollPresence();setInterval(pollPresence,5000);
  request().then(value=>{
    if(value.supported&&valid(value.settings)){
      native=true;settings=value.settings;fill();
      $('screen-hdmi-label').hidden=!value.hdmi_supported;
      $('screen-power-note').textContent=value.hdmi_supported?'Dimming shades the picture. HDMI sleep asks the panel to turn off; some panels keep their backlight on when the signal stops.':'This desktop does not expose display power control. Sleep uses a black screen.';
    }
  }).catch(()=>{});
  setInterval(()=>{if(manualSleep){if(engaged())wake();}else tickScreen();},1000);
})();

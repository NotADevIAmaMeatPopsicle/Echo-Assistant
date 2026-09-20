/* Idle display protection. No camera, microphone sampling, or occupancy tracking. */
(() => {
  'use strict';
  const defaults={dim_after:120,off_after:600,hdmi_sleep:false},times=[0,60,120,300,600,900,1800,3600],key='echo-display-screen-v1';
  let settings={...defaults},native=false,mode='awake',lastActivity=Date.now(),lastPulse=0,blockedPointer=false,blockClick=false,priorFocus=null,manualSleep=false;
  const valid=v=>v&&times.includes(v.dim_after)&&times.includes(v.off_after)&&typeof v.hdmi_sleep==='boolean'&&(!v.off_after||v.dim_after<v.off_after);
  try{const saved=JSON.parse(localStorage.getItem(key));if(valid(saved))settings=saved;}catch{}
  const cover=document.createElement('button');cover.id='screen-cover';cover.type='button';cover.tabIndex=-1;cover.setAttribute('aria-label','Wake display');cover.dataset.mode='awake';cover.hidden=true;document.body.append(cover);
  const card=document.createElement('article');card.id='screen-settings';card.className='card';
  const options=times.map(s=>`<option value="${s}">${s?s<3600?s/60+' minutes':'1 hour':'Never'}</option>`).join('');
  card.innerHTML=`<span class="eyebrow">SCREEN COMFORT</span><h2>A little rest for your display.</h2><form id="screen-form"><label>Dim after<select id="screen-dim">${options}</select></label><label>Sleep after<select id="screen-off">${options}</select></label><label class="check-label screen-wide" id="screen-hdmi-label" hidden><input id="screen-hdmi" type="checkbox">Switch off the display signal when sleeping</label><p class="tiny soft screen-wide" id="screen-power-note">Dimming shades the screen; sleep makes it black. Hardware backlight control depends on your display.</p><p class="tiny soft screen-wide">Tap once to wake, then tap a control to use it. Music and voice stay available. A recognized wake word also wakes the screen. Presence wake needs a connected sensor; none is configured.</p><div class="row screen-wide"><button type="submit" class="pill primary">Save screen settings</button><button type="button" class="pill" id="screen-sleep-now">Sleep now</button></div><p class="tiny soft screen-wide" id="screen-message" role="status"></p></form>`;
  $('page-settings').firstElementChild.after(card);
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
  function wake(){manualSleep=false;lastActivity=Date.now();lastInput=lastActivity;display('awake');pulse();}
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
    if(engaged()){wake();return;}
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
      try{localStorage.setItem(key,JSON.stringify(settings));$('screen-message').textContent='Screen settings saved.';}
      catch{$('screen-message').textContent=native?'Saved on this Pi.':'Settings apply for this tab only.';}
      wake();
    }catch(error){$('screen-message').textContent=error.message;}
    finally{if(submit)submit.disabled=false;}
  };
  $('screen-sleep-now').onclick=()=>{
    lastActivity=Date.now()-(settings.off_after||600)*1000;
    display('sleep');
    // Sleep now stays asleep even if the automatic sleep timer is disabled.
    manualSleep=true;
    if(native&&settings.hdmi_sleep&&settings.off_after)request('POST',{action:'sleep'}).catch(()=>{$('screen-message').textContent='HDMI sleep unavailable; the screen is black.';});
  };
  fill();
  request().then(value=>{
    if(value.supported&&valid(value.settings)){
      native=true;settings=value.settings;fill();
      $('screen-hdmi-label').hidden=!value.hdmi_supported;
      $('screen-power-note').textContent=value.hdmi_supported?'Dimming shades the picture. HDMI sleep asks the panel to turn off; some panels keep their backlight on when the signal stops.':'This desktop does not expose display power control. Sleep uses a black screen.';
    }
  }).catch(()=>{});
  setInterval(()=>{if(manualSleep){if(engaged())wake();}else tickScreen();},1000);
})();

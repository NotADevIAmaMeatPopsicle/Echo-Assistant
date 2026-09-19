'use strict';
const ringCard=document.createElement('article');ringCard.className='card doorbell-card';
ringCard.innerHTML='<span class="eyebrow">AT YOUR DOOR</span><h2>Doorbell activity</h2><p id="doorbell-status" class="tiny soft"></p><div id="doorbell-events"></div>';
experiencePage.append(ringCard);
const ringBanner=document.createElement('aside');ringBanner.id='doorbell-banner';ringBanner.hidden=true;ringBanner.setAttribute('aria-live','polite');document.body.append(ringBanner);
const doorbellChoices=document.createElement('fieldset');doorbellChoices.id='doorbell-choices';$('source-choices').after(doorbellChoices);
endpoints.doorbells='/v1/display/doorbells';
let doorbellSignature='',ringSeen=new Set(),ringBannerId=null;
function ringButtons(e){return `${e.camera?`<button class="pill primary" data-ring-view="${esc(e.id)}">View camera</button>`:''}<button class="pill" data-ring-dismiss="${esc(e.id)}">Dismiss</button>`;}
function renderDoorbells(){
  const state=data.doorbells,ready=fresh('doorbells'),signature=JSON.stringify([ready,state]);
  if(signature===doorbellSignature)return;doorbellSignature=signature;
  const events=ready?(state?.events||[]):[];
  $('doorbell-status').textContent=!ready?'Reconnect to check doorbell activity.':state.status==='not_selected'?'Choose a doorbell trigger under Settings → Calendars & cameras.':state.status==='available'?'Watching selected triggers · silent notifications':state.status==='partial'?'Some selected triggers are unavailable.':state.status==='warming'?'Connecting to selected triggers…':'Doorbell connection unavailable. Showing saved activity.';
  $('doorbell-events').innerHTML=events.map(e=>`<div class="doorbell-event"><div><strong>${esc(e.label)}</strong><p class="tiny soft">${esc(new Date(e.at*1000).toLocaleString())}</p></div><div class="row wrap">${ringButtons(e)}</div></div>`).join('')||empty('No saved rings. Camera views open only when you choose.');
  const recent=events.find(e=>!ringSeen.has(e.id)&&Date.now()-e.at*1000>=0&&Date.now()-e.at*1000<30000);
  ringSeen=new Set(events.map(e=>e.id));
  if(recent){ringBannerId=recent.id;ringBanner.innerHTML=`<span class="eyebrow">DOORBELL</span><h3>${esc(recent.label)}</h3><p class="tiny soft">Someone is at the door.</p><div class="row wrap">${ringButtons(recent)}</div>`;ringBanner.hidden=false;}
  if(!events.some(e=>e.id===ringBannerId)){ringBanner.hidden=true;ringBannerId=null;}
}
extensions.push(renderDoorbells);
document.addEventListener('click',async event=>{
  const view=event.target.closest('[data-ring-view]'),dismiss=event.target.closest('[data-ring-dismiss]');
  if(dismiss){if(fresh('doorbells'))action(()=>api('/v1/display/doorbells/events/'+dismiss.dataset.ringDismiss,{},'DELETE'),'Doorbell event dismissed.');return;}
  if(!view||!fresh('doorbells'))return;
  const ring=data.doorbells?.events.find(e=>e.id===view.dataset.ringView);if(!ring?.camera)return;
  try{
    if(!$('ambient').hidden)ambient(false);
    page('day');data.sources=await api('/v1/display/sources');received.sources=Date.now();renderSources();
    if(!data.sources.items.some(s=>s.entity_id===ring.camera&&s.kind==='camera'&&s.available))throw new Error('This camera is no longer available to the display.');
    stopCamera();$('camera-choice').value=ring.camera;$('camera-mode').value='live';renderSources();guardButtons();$('camera-open').click();
    document.querySelector('.camera-card').scrollIntoView({block:'center',behavior:'smooth'});ringBanner.hidden=true;
  }catch(error){toast(error.message);}
});
function renderDoorbellChoices(state){
  const selected=new Map((state.sources.doorbells||[]).map(d=>[d.trigger,d]));
  const triggers=state.items.filter(i=>['event','binary_sensor'].includes(i.kind));
  for(const [id,binding] of selected)if(!triggers.some(i=>i.entity_id===id))triggers.push({entity_id:id,name:binding.label,available:false});
  const cameras=state.items.filter(i=>i.kind==='camera');
  doorbellChoices.innerHTML=`<legend>Doorbell notifications</legend><p class="tiny soft">Choose only entities that report a doorbell press. Event entities are preferred; short binary-sensor pulses may be missed. Nothing below is enabled automatically.</p>${triggers.map(i=>{const chosen=selected.get(i.entity_id);return `<div class="doorbell-binding"><label class="check-label"><input type="checkbox" data-ring-trigger value="${esc(i.entity_id)}" ${chosen?'checked':''}>${esc(i.name)}${i.available?'':' · unavailable'}</label><small class="soft">${esc(i.entity_id)}</small><div class="two-columns"><label>Display name<input data-ring-label maxlength="60" value="${esc(chosen?.label||i.name.slice(0,60))}"></label><label>Associated camera<select data-ring-camera><option value="">No camera</option>${cameras.map(c=>`<option value="${esc(c.entity_id)}" ${chosen?.camera===c.entity_id?'selected':''}>${esc(c.name)}</option>`).join('')}</select></label></div></div>`;}).join('')||empty('No event or binary-sensor triggers found in Home Assistant.')}`;
}
function doorbellSelection(){
  const cameras=new Set([...$('source-choices').querySelectorAll('[data-source-read]:checked')].map(i=>i.value));
  return [...doorbellChoices.querySelectorAll('.doorbell-binding')].filter(row=>row.querySelector('[data-ring-trigger]').checked).map(row=>{
    const camera=row.querySelector('[data-ring-camera]').value,label=row.querySelector('[data-ring-label]').value.trim();
    if(camera&&!cameras.has(camera))throw new Error('Share the associated doorbell camera above, or choose No camera.');
    if(!label)throw new Error('Give each selected doorbell a display name.');
    return {trigger:row.querySelector('[data-ring-trigger]').value,label,camera:camera||null};
  });
}

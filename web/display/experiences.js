'use strict';
const experiencePage=document.createElement('section');
experiencePage.id='page-day'; experiencePage.className='page'; experiencePage.hidden=true;
experiencePage.innerHTML=`<div class="two-columns"><article class="card agenda-card"><span class="eyebrow">A LITTLE LOOK AHEAD</span><h2>Your agenda</h2><form id="agenda-form" class="inline-form"><label>From<input id="agenda-date" type="date" required></label><label>Days<select id="agenda-days"><option value="1">Today</option><option value="7" selected>A week</option><option value="31">A month</option></select></label><button class="pill" type="submit">Show</button></form><p id="agenda-status" class="tiny soft"></p><div id="agenda-events"></div></article><article class="card camera-card"><span class="eyebrow">A VIEW FROM HOME</span><h2>Cameras & doorbells</h2><div class="camera-selectors"><label>Camera<select id="camera-choice"><option value="">Choose a camera</option></select></label><label>View mode<select id="camera-mode"><option value="live">Live stream</option><option value="snapshots">Snapshots · every 5 seconds</option></select></label></div><div class="camera-frame"><img id="camera-frame" alt="Selected camera view" hidden><p id="camera-placeholder" class="empty">Choose an approved camera, then open its view.</p></div><p id="camera-status" class="tiny soft">Live MJPEG from Home Assistant. Choose snapshots if streaming is unsupported.</p><div class="row"><button id="camera-open" class="pill primary" type="button" data-requires="sources">Open view</button><button id="camera-close" class="pill" type="button">Close view</button></div><p class="tiny soft">No microphone, recording, or camera audio. Closing the view clears its last image.</p></article></div>`;
document.querySelector('main').append(experiencePage);
const dayNav=document.createElement('button'); dayNav.dataset.page='day'; dayNav.innerHTML=icon('sun')+'<span>My day</span>';
$('navigation').insertBefore(dayNav,$('navigation').querySelector('[data-page="planner"]'));
titles.day='A little perspective.';
$('agenda-date').value=localDate(new Date());
endpoints.sources='/v1/display/sources'; pageEndpoints.sources='day';
function agendaEndpoint(){endpoints.agenda='/v1/display/agenda?'+new URLSearchParams({start:$('agenda-date').value,days:$('agenda-days').value});}
agendaEndpoint(); pageEndpoints.agenda='day';
const sourceCard=document.createElement('article');sourceCard.className='card pairing-card';sourceCard.hidden=true;
sourceCard.innerHTML='<span class="eyebrow">CHOOSE WHAT IS SHARED</span><h2>Calendars & cameras</h2><p class="soft">Choose sources for your paired displays. Nothing is selected automatically. Calendar accounts and doorbell cameras are connected through Home Assistant.</p><button class="pill" id="source-load" type="button">Load sources</button><form id="source-form" hidden><p id="source-status" class="tiny soft"></p><div id="source-choices"></div><button class="pill primary" type="submit">Save display sources</button></form>';
$('page-settings').append(sourceCard);
const presenceChoices=document.createElement('fieldset');presenceChoices.id='source-presence';
presenceChoices.innerHTML='<legend>Presence sensors</legend><p class="tiny soft">Share motion or occupancy sensors here, then choose one under Screen comfort on each display. Sharing does not activate screen wake automatically.</p><div id="source-presence-choices"></div>';
$('source-form').querySelector('button[type="submit"]').before(presenceChoices);
let sourceRevision=null, cameraUrl=null, cameraActive=false, cameraBusy=false, cameraGeneration=0, cameraAbort=null;
function stopCamera(){cameraAbort?.abort();cameraAbort=null;cameraActive=false;cameraGeneration++;$('camera-frame').hidden=true;$('camera-frame').removeAttribute('src');if(cameraUrl)URL.revokeObjectURL(cameraUrl);cameraUrl=null;$('camera-placeholder').hidden=false;}
function localEventDate(event){return event.all_day ? event.start : localDate(new Date(event.start));}
function renderAgenda(){
  const state=data.agenda;
  const selected=data.sources?.items.filter(s=>s.kind==='calendar') || [];
  $('agenda-status').textContent=!state ? 'Agenda unavailable. Check the host connection.' : state.status==='not_configured' ? 'Connect Home Assistant in the owner workspace.' : !selected.length ? 'Choose calendars under Settings → Calendars & cameras.' : state.status==='partial' ? 'Some calendars could not be reached. Showing available events.' : 'From your selected Home Assistant calendars.';
  const start=$('agenda-date').value, until=new Date(start+'T12:00:00');until.setDate(until.getDate()+Number($('agenda-days').value));const end=localDate(until);
  const events=(state?.events || []).filter(e=>localEventDate(e)<end && (e.all_day ? e.end>start : localDate(new Date(e.end))>=start));
  let day='';
  $('agenda-events').innerHTML=events.length ? events.map(e=>{
    const key=localEventDate(e), heading=key!==day ? `<h3 class="agenda-day">${esc(new Date(key+'T12:00:00').toLocaleDateString(undefined,{weekday:'long',month:'short',day:'numeric'}))}</h3>` : ''; day=key;
    return `${heading}<div class="agenda-event"><span class="agenda-time">${e.all_day ? 'All day' : esc(new Date(e.start).toLocaleTimeString([],{hour:'numeric',minute:'2-digit'}))}</span><div><strong>${esc(e.title)}</strong><p class="tiny soft">${esc(e.calendar_name)}${e.location ? ' · '+esc(e.location) : ''}${e.recurring?' · Repeats':''}</p></div><button class="pill calendar-details" type="button" data-event-id="${esc(e.id)}">Details</button></div>`;
  }).join('') : empty(state ? 'Nothing on the agenda for these days.' : 'Reconnect to load your agenda.');
}
function renderSources(){
  sourceCard.hidden=data.session?.role!=='owner';
  if(experiencePage.hidden){if(cameraActive)stopCamera();return;}
  const cameras=data.sources?.items.filter(s=>s.kind==='camera') || [], selected=$('camera-choice').value;
  if(document.activeElement!==$('camera-choice')){
    $('camera-choice').innerHTML='<option value="">Choose a camera</option>'+cameras.map(c=>`<option value="${esc(c.entity_id)}">${esc(c.name)}${c.available ? '' : ' · unavailable'}</option>`).join('');
    $('camera-choice').value=cameras.some(c=>c.entity_id===selected) ? selected : '';
  }
  if(!fresh('sources') || !cameras.some(c=>c.entity_id===selected && c.available)){if(cameraActive)stopCamera();}
  $('camera-open').dataset.unavailable=String(!cameras.some(c=>c.entity_id===$('camera-choice').value && c.available));
  if(!cameras.length)$('camera-placeholder').textContent='Choose cameras under Settings → Calendars & cameras.';
  renderAgenda();
}
extensions.push(renderSources);
$('agenda-form').onsubmit=event=>{event.preventDefault();agendaEndpoint();delete data.agenda;refresh();};
$('source-load').onclick=()=>action(async()=>{
  const state=await api('/v1/display/source-settings');sourceRevision=state.revision;
  const selected=new Set([...state.sources.calendars,...state.sources.cameras]),writers=new Set(state.sources.writable_calendars||[]),managers=new Set(state.sources.managed_calendars||[]);
  const items=state.items.filter(i=>['camera','calendar'].includes(i.kind));for(const id of selected)if(!items.some(i=>i.entity_id===id))items.push({entity_id:id,name:id,available:false});
  $('source-status').textContent=state.status==='available' ? 'Checked sources are shared with paired displays. Uncheck to remove access.' : 'Home Assistant is unavailable or not configured. You can clear existing selections.';
  $('source-choices').innerHTML=items.map(i=>`<div class="source-permissions"><label class="source-choice"><input type="checkbox" data-source-read value="${esc(i.entity_id)}" ${selected.has(i.entity_id)?'checked':''}><span>${esc(i.name)}<small class="soft">${esc(i.entity_id)}${i.available ? '' : ' · unavailable'}</small></span></label>${i.can_create||writers.has(i.entity_id)?`<label class="check-label calendar-write-choice"><input type="checkbox" data-source-write value="${esc(i.entity_id)}" ${writers.has(i.entity_id)?'checked':''}>Allow event creation from Echo displays</label>`:''}${i.can_edit||i.can_delete||managers.has(i.entity_id)?`<label class="check-label calendar-write-choice"><input type="checkbox" data-source-manage value="${esc(i.entity_id)}" ${managers.has(i.entity_id)?'checked':''}>Allow edits and deletion of existing events</label>`:''}</div>`).join('') || empty('No calendar or camera entities were found.');
  renderDoorbellChoices(state);
  const shared=new Set(state.sources.presence_sensors||[]),sensors=state.items.filter(i=>i.can_detect_presence);
  for(const id of shared)if(!sensors.some(i=>i.entity_id===id))sensors.push({entity_id:id,name:id,available:false});
  $('source-presence-choices').innerHTML=sensors.map(i=>`<label class="source-choice"><input type="checkbox" value="${esc(i.entity_id)}" ${shared.has(i.entity_id)?'checked':''}><span>${esc(i.name)}<small class="soft">${esc(i.entity_id)}${i.available?'':' · unavailable'}</small></span></label>`).join('')||empty('No motion or occupancy sensors are connected to Home Assistant.');
  $('source-form').hidden=false;
},'Sources loaded.');
$('source-form').onsubmit=event=>{event.preventDefault();if(sourceRevision===null)return;action(async()=>{
  const selected=[...$('source-choices').querySelectorAll('[data-source-read]:checked')].map(i=>i.value);
  const writers=[...$('source-choices').querySelectorAll('[data-source-write]:checked')].map(i=>i.value);
  const managed_calendars=[...$('source-choices').querySelectorAll('[data-source-manage]:checked')].map(i=>i.value);
  const presence_sensors=[...$('source-presence-choices').querySelectorAll('input:checked')].map(i=>i.value);
  const state=await api('/v1/display/source-settings',{revision:sourceRevision,sources:{calendars:selected.filter(i=>i.startsWith('calendar.')),cameras:selected.filter(i=>i.startsWith('camera.')),writable_calendars:writers,managed_calendars,doorbells:doorbellSelection(),presence_sensors}},'PUT');
  sourceRevision=state.revision;stopCamera();
},'Display sources saved.');};
$('source-choices').addEventListener('change',event=>{
  const row=event.target.closest('.source-permissions');if(!row)return;
  if((event.target.hasAttribute('data-source-write')||event.target.hasAttribute('data-source-manage'))&&event.target.checked)row.querySelector('[data-source-read]').checked=true;
  if(event.target.hasAttribute('data-source-read')&&!event.target.checked){for(const write of row.querySelectorAll('[data-source-write],[data-source-manage]'))write.checked=false;}
});
$('camera-choice').onchange=()=>{stopCamera();$('camera-placeholder').textContent='Press Open view to start the selected view.';renderSources();guardButtons();};
// Decode only the normalized, length-delimited JPEG parts emitted by Echo.
async function liveCamera(response,generation,controller){
  if(!response.headers.get('content-type')?.startsWith('multipart/x-mixed-replace'))throw new Error('Live view is unsupported. Try snapshots.');
  const reader=response.body.getReader();let buffer=new Uint8Array(),length=null,frames=0;
  let idle=setTimeout(()=>controller.abort('timeout'),15000);
  try{
    while(cameraActive&&generation===cameraGeneration){
      const {value,done}=await reader.read();if(done)throw new Error('Live stream ended. Open again to reconnect, or try snapshots.');
      clearTimeout(idle);idle=setTimeout(()=>controller.abort('timeout'),15000);
      if(buffer.length+value.length>5100000)throw new Error('Camera frame is too large.');
      const next=new Uint8Array(buffer.length+value.length);next.set(buffer);next.set(value,buffer.length);buffer=next;
      while(true){
        if(length===null){
          let split=-1;for(let i=0;i<buffer.length-3;i++)if(buffer[i]===13&&buffer[i+1]===10&&buffer[i+2]===13&&buffer[i+3]===10){split=i;break;}
          if(split<0){if(buffer.length>1024)throw new Error('Invalid camera stream.');break;}
          const header=new TextDecoder().decode(buffer.slice(0,split)),match=/Content-Length: (\d+)/i.exec(header);
          if(!match||!header.includes('Content-Type: image/jpeg'))throw new Error('Invalid camera stream.');
          length=Number(match[1]);if(length<4||length>5000000)throw new Error('Camera frame is too large.');
          buffer=buffer.slice(split+4);
        }
        if(buffer.length<length)break;
        if(!cameraActive||generation!==cameraGeneration)return;
        showCamera(new Blob([buffer.slice(0,length)],{type:'image/jpeg'}),'Live · '+new Date().toLocaleTimeString());
        buffer=buffer.slice(length);length=null;frames++;
      }
    }
  }finally{clearTimeout(idle);await reader.cancel().catch(()=>{});}
}
function showCamera(blob,status){
  const url=URL.createObjectURL(blob),old=cameraUrl;cameraUrl=url;
  $('camera-frame').src=url;$('camera-frame').hidden=false;$('camera-placeholder').hidden=true;$('camera-status').textContent=status;
  if(old)URL.revokeObjectURL(old);
  $('camera-frame').onerror=()=>{if(cameraUrl!==url)return;stopCamera();$('camera-placeholder').textContent='Camera image could not be decoded. Try snapshots or check the camera.';};
}
async function cameraFrame(){
  if(!cameraActive||cameraBusy||experiencePage.hidden||document.hidden)return;
  const generation=cameraGeneration,identifier=$('camera-choice').value,live=$('camera-mode').value==='live';
  const controller=new AbortController();cameraAbort=controller;cameraBusy=true;
  const timeout=setTimeout(()=>controller.abort(live?'renew':'timeout'),live?100000:10000);
  let renew=false;
  try{
    $('camera-status').textContent=live?'Connecting live view…':'Refreshing snapshot…';
    const response=await fetch('/v1/display/cameras/'+encodeURIComponent(identifier)+(live?'/stream':'/snapshot'),{credentials:'same-origin',cache:'no-store',signal:controller.signal});
    if(!response.ok)throw new Error(response.status===403||response.status===401?'Camera access was removed. Check source permissions.':'Camera unavailable. Try snapshots or check its Home Assistant integration.');
    if(live)await liveCamera(response,generation,controller);
    else{
      const blob=await response.blob();if(!['image/jpeg','image/png','image/webp'].includes(blob.type)||blob.size>5000000)throw new Error('Camera returned an unsupported image.');
      if(cameraActive&&generation===cameraGeneration)showCamera(blob,'Latest snapshot · '+new Date().toLocaleTimeString());
    }
  }catch(error){
    if(generation===cameraGeneration){
      if(controller.signal.reason==='renew')renew=true;
      else{stopCamera();$('camera-status').textContent='View stopped.';$('camera-placeholder').textContent=controller.signal.reason==='timeout'?'Camera stopped sending frames. Open again to retry.':error.message||'Camera connection ended. Open again to retry.';}
    }
  }finally{clearTimeout(timeout);cameraBusy=false;if(cameraAbort===controller)cameraAbort=null;}
  if(cameraActive&&generation!==cameraGeneration){cameraFrame();return;}
  if(renew&&cameraActive&&generation===cameraGeneration)cameraFrame();
}
$('camera-open').onclick=()=>{if(!fresh('sources')||!$('camera-choice').value)return;cameraAbort?.abort();cameraActive=true;cameraGeneration++;cameraFrame();};
$('camera-close').onclick=()=>{stopCamera();$('camera-placeholder').textContent='View closed.';$('camera-status').textContent='Camera closed.';};
$('camera-mode').onchange=()=>{stopCamera();$('camera-placeholder').textContent='Press Open view to start the selected view.';};
setInterval(()=>{if($('camera-mode').value==='snapshots')cameraFrame();},5000);
document.addEventListener('visibilitychange',()=>{if(document.hidden&&cameraActive)stopCamera();});
document.addEventListener('echo:page',event=>{if(event.detail!=='day')stopCamera();});
new MutationObserver(()=>{if(!$('ambient').hidden)stopCamera();}).observe($('ambient'),{attributes:true,attributeFilter:['hidden']});

$('agenda-events').addEventListener('click',event=>{const id=event.target.closest('[data-event-id]')?.dataset.eventId;const item=data.agenda?.events.find(i=>i.id===id);if(item&&typeof showCalendarDetails==='function')showCalendarDetails(item);});

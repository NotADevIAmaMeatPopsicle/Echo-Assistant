'use strict';
const experiencePage=document.createElement('section');
experiencePage.id='page-day'; experiencePage.className='page'; experiencePage.hidden=true;
experiencePage.innerHTML=`<div class="two-columns"><article class="card agenda-card"><span class="eyebrow">A LITTLE LOOK AHEAD</span><h2>Your agenda</h2><form id="agenda-form" class="inline-form"><label>From<input id="agenda-date" type="date" required></label><label>Days<select id="agenda-days"><option value="1">Today</option><option value="7" selected>A week</option><option value="31">A month</option></select></label><button class="pill" type="submit">Show</button></form><p id="agenda-status" class="tiny soft"></p><div id="agenda-events"></div></article><article class="card camera-card"><span class="eyebrow">A VIEW FROM HOME</span><h2>Cameras & doorbells</h2><label>Camera<select id="camera-choice"><option value="">Choose a camera</option></select></label><div class="camera-frame"><img id="camera-frame" alt="Selected camera snapshot" hidden><p id="camera-placeholder" class="empty">Choose an approved camera, then open its view.</p></div><p id="camera-status" class="tiny soft">Snapshots refresh every five seconds while this page is open.</p><div class="row"><button id="camera-open" class="pill primary" type="button" data-requires="sources">Open view</button><button id="camera-close" class="pill" type="button">Close view</button></div><p class="tiny soft">No microphone, recording, or camera audio. Closing the view clears its last image.</p></article></div>`;
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
let sourceRevision=null, cameraUrl=null, cameraActive=false, cameraBusy=false, cameraGeneration=0;
function stopCamera(){cameraActive=false;cameraGeneration++;$('camera-frame').hidden=true;$('camera-frame').removeAttribute('src');if(cameraUrl)URL.revokeObjectURL(cameraUrl);cameraUrl=null;$('camera-placeholder').hidden=false;}
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
    return `${heading}<div class="agenda-event"><span class="agenda-time">${e.all_day ? 'All day' : esc(new Date(e.start).toLocaleTimeString([],{hour:'numeric',minute:'2-digit'}))}</span><div><strong>${esc(e.title)}</strong><p class="tiny soft">${esc(e.calendar_name)}${e.location ? ' · '+esc(e.location) : ''}</p></div></div>`;
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
  const selected=new Set([...state.sources.calendars,...state.sources.cameras]);
  const items=[...state.items];for(const id of selected)if(!items.some(i=>i.entity_id===id))items.push({entity_id:id,name:id,available:false});
  $('source-status').textContent=state.status==='available' ? 'Checked sources are shared with paired displays. Uncheck to remove access.' : 'Home Assistant is unavailable or not configured. You can clear existing selections.';
  $('source-choices').innerHTML=items.map(i=>`<label class="source-choice"><input type="checkbox" value="${esc(i.entity_id)}" ${selected.has(i.entity_id)?'checked':''}><span>${esc(i.name)}<small class="soft">${esc(i.entity_id)}${i.available ? '' : ' · unavailable'}</small></span></label>`).join('') || empty('No calendar or camera entities were found.');
  $('source-form').hidden=false;
},'Sources loaded.');
$('source-form').onsubmit=event=>{event.preventDefault();if(sourceRevision===null)return;action(async()=>{
  const selected=[...$('source-choices').querySelectorAll('input:checked')].map(i=>i.value);
  const state=await api('/v1/display/source-settings',{revision:sourceRevision,sources:{calendars:selected.filter(i=>i.startsWith('calendar.')),cameras:selected.filter(i=>i.startsWith('camera.'))}},'PUT');
  sourceRevision=state.revision;stopCamera();
},'Display sources saved.');};
$('camera-choice').onchange=()=>{stopCamera();$('camera-placeholder').textContent='Press Open view to start snapshots.';renderSources();guardButtons();};
async function cameraFrame(){
  if(!cameraActive || cameraBusy || experiencePage.hidden || document.hidden)return;
  const generation=cameraGeneration, identifier=$('camera-choice').value;
  cameraBusy=true;
  try{
    const response=await fetch('/v1/display/cameras/'+encodeURIComponent(identifier)+'/snapshot',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(10000)});
    if(!response.ok)throw new Error(response.status===403 || response.status===401 ? 'Camera access was removed. Open Settings to check permissions.' : 'Camera unavailable. Close and reopen the view to retry.');
    const blob=await response.blob();if(!['image/jpeg','image/png','image/webp'].includes(blob.type) || blob.size>5000000)throw new Error('Camera returned an unsupported image.');
    if(!cameraActive || generation!==cameraGeneration)return;
    const url=URL.createObjectURL(blob);if(cameraUrl)URL.revokeObjectURL(cameraUrl);cameraUrl=url;
    $('camera-frame').src=url;$('camera-frame').hidden=false;$('camera-placeholder').hidden=true;$('camera-status').textContent='Latest snapshot · '+new Date().toLocaleTimeString();
  }catch(error){if(generation===cameraGeneration){stopCamera();$('camera-placeholder').textContent=error.message;}}
  finally{cameraBusy=false;}
}
$('camera-open').onclick=()=>{if(!fresh('sources') || !$('camera-choice').value)return;cameraActive=true;cameraGeneration++;cameraFrame();};
$('camera-close').onclick=()=>{stopCamera();$('camera-placeholder').textContent='View closed.';};
setInterval(cameraFrame,5000);
document.addEventListener('visibilitychange',()=>{if(document.hidden && cameraActive)stopCamera();});

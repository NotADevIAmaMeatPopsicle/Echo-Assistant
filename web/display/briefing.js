'use strict';
const briefingCard=document.createElement('article');briefingCard.className='card daily-briefing';
briefingCard.innerHTML='<div class="row spread"><div><span class="eyebrow">THE DAY, AT A GLANCE</span><h2>A little more prepared.</h2></div><button class="pill" id="briefing-chat" type="button">Ask Echo</button></div><p id="briefing-summary" class="soft">Gathering your day…</p><div id="briefing-facts" class="briefing-facts"></div><p id="briefing-freshness" class="tiny soft"></p>';
experiencePage.prepend(briefingCard);
endpoints.briefing='/v1/display/briefing?'+new URLSearchParams({timezone:Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC'});pageEndpoints.briefing='day';
extensions.push(()=>{
  const state=data.briefing;
  $('briefing-summary').textContent=state?.text||'Your briefing is unavailable. Check the host connection.';
  $('briefing-freshness').textContent=state?.generated_at?`Updated ${new Date(state.generated_at*1000).toLocaleTimeString([],{hour:'numeric',minute:'2-digit'})} · ${state.timezone}${state.partial?' · some sources unavailable':''}`:'';
  $('briefing-facts').innerHTML=state?.sources?[
    ['Calendar',state.sources.calendar==='available'||state.sources.calendar==='partial'?`${state.event_count} remaining today`:human(state.sources.calendar)],
    ['Reminders',state.sources.reminders==='available'?`${state.reminders.length} today`:'Unavailable'],
    ['Your lists',state.sources.lists==='available'?`${state.task_count} tasks · ${state.shopping_count} shopping`:'Unavailable']
  ].map(([label,value])=>`<div><span class="eyebrow">${label}</span><strong>${esc(value)}</strong></div>`).join(''):'';
});
$('briefing-chat').onclick=()=>{page('assistant');$('chat-text').value='Give me my daily briefing';$('chat-text').focus();};

const createButton=document.createElement('button');createButton.id='calendar-create';createButton.className='pill primary';createButton.type='button';createButton.textContent='New event';
$('agenda-form').after(createButton);
const eventDialog=document.createElement('dialog');eventDialog.id='calendar-event-dialog';
eventDialog.innerHTML=`<form id="calendar-event-form"><div class="row spread"><div><span class="eyebrow">MAKE A LITTLE SPACE</span><h2>New calendar event</h2></div><button type="button" class="icon-button" id="calendar-event-close" aria-label="Close event form">×</button></div><fieldset id="calendar-event-fields"><label>Calendar<select id="event-calendar" required></select></label><label>Title<input id="event-title" maxlength="200" required placeholder="What’s happening?"></label><label class="check-label"><input id="event-all-day" type="checkbox">All day</label><div class="two-columns"><label>Starts<input id="event-start" type="datetime-local" required></label><label id="event-end-label">Ends<input id="event-end" type="datetime-local" required></label></div><label>Time zone<input id="event-timezone" required maxlength="80"></label><label>Location<input id="event-location" maxlength="300" placeholder="Optional"></label><label>Notes<textarea id="event-description" maxlength="2000" rows="2" placeholder="Optional"></textarea></label><details class="tiny soft"><summary>Repeated clock-change times</summary><p>For an hour that occurs twice when clocks go back, choose its first or second occurrence.</p><div class="two-columns"><label>Start occurrence<select id="event-start-fold"><option value="0">First</option><option value="1">Second</option></select></label><label>End occurrence<select id="event-end-fold"><option value="0">First</option><option value="1">Second</option></select></label></div></details></fieldset><p id="calendar-event-status" class="tiny soft" role="status">This creates an event in the selected calendar through Home Assistant.</p><div class="row spread"><button class="pill" id="calendar-event-cancel" type="button">Close</button><button class="pill primary" id="calendar-event-submit" type="submit">Create event</button></div></form>`;
document.body.append(eventDialog);
const eventScroll=document.createElement('div');eventScroll.id='calendar-event-scroll';
$('calendar-event-fields').before(eventScroll);eventScroll.append($('calendar-event-fields'));
let eventDraft=null;
createButton.onclick=()=>{
  const writable=(data.sources?.items||[]).filter(i=>i.kind==='calendar'&&i.writable&&i.available);
  if(!fresh('sources')||!writable.length)return toast('Enable event creation for a calendar under Settings → Calendars & cameras.');
  eventDraft=null;$('calendar-event-form').reset();$('calendar-event-fields').disabled=false;$('calendar-event-submit').disabled=false;$('calendar-event-submit').textContent='Create event';
  $('event-start').type=$('event-end').type='datetime-local';
  $('event-calendar').innerHTML=writable.map(i=>`<option value="${esc(i.entity_id)}">${esc(i.name)}</option>`).join('');
  const when=new Date();when.setMinutes(0,0,0);when.setHours(when.getHours()+1);const end=new Date(when.getTime()+3600000);
  const local=value=>`${localDate(value)}T${String(value.getHours()).padStart(2,'0')}:${String(value.getMinutes()).padStart(2,'0')}`;
  $('event-start').value=local(when);$('event-end').value=local(end);$('event-timezone').value=Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC';
  $('calendar-event-status').textContent='This creates an event in the selected calendar through Home Assistant.';
  eventDialog.showModal();$('event-title').focus();
};
function closeEvent(){if($('calendar-event-submit').dataset.sending==='true')return;eventDialog.close();createButton.focus();}
$('calendar-event-close').onclick=$('calendar-event-cancel').onclick=closeEvent;
eventDialog.addEventListener('cancel',e=>{if($('calendar-event-submit').dataset.sending==='true')e.preventDefault();});
$('event-all-day').onchange=()=>{
  for(const id of ['event-start','event-end']){const value=$(id).value;$(id).type=$('event-all-day').checked?'date':'datetime-local';$(id).value=$('event-all-day').checked?value.slice(0,10):value.slice(0,10)+(id==='event-start'?'T10:00':'T11:00');}
  $('calendar-event-status').textContent=$('event-all-day').checked?'For all-day events, Ends is the last included day.':'This creates an event in the selected calendar through Home Assistant.';
};
$('calendar-event-form').onsubmit=async event=>{
  event.preventDefault();const button=$('calendar-event-submit');if(button.dataset.sending==='true')return;
  if(!eventDraft){
    let end=$('event-end').value;
    if($('event-all-day').checked){const day=new Date(end+'T12:00:00');day.setDate(day.getDate()+1);end=localDate(day);}
    eventDraft={revision:data.sources.revision,request_id:crypto.randomUUID().replaceAll('-',''),event:{calendar:$('event-calendar').value,title:$('event-title').value,description:$('event-description').value,location:$('event-location').value,start:$('event-start').value,end,all_day:$('event-all-day').checked,timezone:$('event-timezone').value,start_fold:Number($('event-start-fold').value),end_fold:Number($('event-end-fold').value)}};
  }
  button.dataset.sending='true';button.disabled=true;$('calendar-event-fields').disabled=true;$('calendar-event-status').textContent='Sending to your calendar…';
  try{const result=await api('/v1/display/calendar/events',eventDraft);$('calendar-event-status').textContent=result.text;button.textContent=result.status==='accepted'?'Accepted':'Check your calendar';delete data.briefing;await refresh();}
  catch(error){
    if([403,409,422].includes(error.status)){eventDraft=null;$('calendar-event-fields').disabled=false;button.textContent='Create event';$('calendar-event-status').textContent=error.message+' Review the fields and calendar permissions, then try again.';}
    else{$('calendar-event-status').textContent=error.message+' Check the agenda if the connection was lost. Retrying sends the same request identifier.';button.textContent='Retry same request';}
    button.disabled=false;
  }
  finally{button.dataset.sending='false';}
};

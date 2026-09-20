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
let editingEvent=null;
let editingScope='single';
let calendarDraftRequest=null;
const recurrenceFields=document.createElement('div');recurrenceFields.className='calendar-recurrence';
recurrenceFields.innerHTML='<label>Repeat<select id="event-repeat"><option value="">Does not repeat</option><option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option><option value="yearly">Yearly</option></select></label><div id="event-repeat-options" class="two-columns" hidden><label>Every<input id="event-interval" type="number" min="1" max="99" value="1"></label><label>Total occurrences<input id="event-count" type="number" min="2" max="366" value="10"></label></div><p id="event-repeat-note" class="tiny soft" hidden>Includes the first event. Monthly and yearly schedules skip dates that do not exist. Timed repeats use the Home Assistant time zone.</p>';
$('calendar-event-fields').append(recurrenceFields);
$('event-repeat').onchange=()=>{$('event-repeat-options').hidden=$('event-repeat-note').hidden=!$('event-repeat').value;};
const draftComposer=document.createElement('details');draftComposer.className='calendar-draft-composer';
draftComposer.innerHTML='<summary>Describe an event in your own words</summary><label for="calendar-draft-text">Describe the event<textarea id="calendar-draft-text" maxlength="2000" rows="2" placeholder="Lunch with Sam tomorrow at noon for an hour"></textarea></label><button class="pill" id="calendar-draft-build" type="button">Draft from words</button><p class="tiny soft">Uses your configured model. Review the fields below before creating anything.</p>';
eventScroll.prepend(draftComposer);
const draftNotes=document.createElement('ul');draftNotes.id='calendar-draft-notes';draftNotes.className='tiny soft';draftComposer.after(draftNotes);
function openCalendarEvent(draft=null){
  if(draft&&(!Number.isFinite(draft.expires_at)||draft.expires_at*1000<Date.now()))return toast('That draft expired. Describe the event again with the current date.');
  const writable=(data.sources?.items||[]).filter(i=>i.kind==='calendar'&&i.writable&&i.available);
  draftNotes.replaceChildren();draftComposer.open=false;$('calendar-draft-build').disabled=false;
  editingEvent=null;editingScope='single';draftComposer.hidden=false;recurrenceFields.hidden=false;eventDialog.querySelector('h2').textContent='New calendar event';
  eventDraft=null;$('calendar-event-form').reset();$('event-calendar').disabled=$('event-start').disabled=$('event-start-fold').disabled=$('event-all-day').disabled=false;$('event-repeat').onchange();$('calendar-event-fields').disabled=false;$('calendar-event-submit').disabled=!fresh('sources')||!writable.length;$('calendar-event-submit').textContent='Create event';
  $('event-start').type=$('event-end').type='datetime-local';
  $('event-calendar').innerHTML='<option value="">Choose a calendar</option>'+writable.map(i=>`<option value="${esc(i.entity_id)}">${esc(i.name)}</option>`).join('');
  if(writable.length===1)$('event-calendar').value=writable[0].entity_id;
  const when=new Date();when.setMinutes(0,0,0);when.setHours(when.getHours()+1);const end=new Date(when.getTime()+3600000);
  const local=value=>`${localDate(value)}T${String(value.getHours()).padStart(2,'0')}:${String(value.getMinutes()).padStart(2,'0')}`;
  $('event-start').value=local(when);$('event-end').value=local(end);$('event-timezone').value=Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC';
  $('calendar-event-status').textContent=writable.length?'This creates an event in the selected calendar through Home Assistant.':'You can draft an event now. Enable a writable calendar under Settings → Calendars & cameras before creating it.';
  if(draft)applyCalendarDraft(draft);
  eventDialog.showModal();$('event-title').focus();
}
createButton.onclick=()=>openCalendarEvent();
function applyCalendarDraft(draft){
  const event=draft.event;if(!event||typeof event!=='object')return;
  eventDraft=null;$('event-all-day').checked=event.all_day===true;
  $('event-start').type=$('event-end').type=event.all_day?'date':'datetime-local';
  for(const key of ['title','start','end','timezone','location','description','calendar'])$('event-'+key).value=typeof event[key]==='string'?event[key]:'';
  if(event.all_day&&event.end){const last=new Date(event.end+'T12:00:00');last.setDate(last.getDate()-1);$('event-end').value=localDate(last);}
  draftNotes.replaceChildren();for(const question of draft.questions||[]){const item=document.createElement('li');item.textContent=question;draftNotes.append(item);}
  draftComposer.open=false;eventScroll.scrollTop=0;
  $('calendar-event-status').textContent='Draft only. Nothing has been saved. Review the fields and any questions above.';
}
function attachCalendarDraft(message,draft){
  const button=document.createElement('button');button.className='pill';button.type='button';button.textContent='Review calendar draft';
  button.onclick=()=>openCalendarEvent(draft);message.append(button);
}
$('calendar-draft-build').onclick=async()=>{
  const text=$('calendar-draft-text').value.trim();if(!text||calendarDraftRequest||$('calendar-event-submit').dataset.sending==='true')return;
  const controller=new AbortController();calendarDraftRequest=controller;
  $('calendar-draft-build').disabled=true;$('calendar-event-submit').disabled=true;$('calendar-event-fields').disabled=true;
  $('calendar-event-status').textContent='Drafting the event. Nothing is being saved…';
  try{
    const result=await api('/v1/display/calendar/draft',{text,timezone:$('event-timezone').value||Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC'},'POST',controller.signal);
    if(calendarDraftRequest!==controller||!eventDialog.open)return;
    if(result.calendar_draft)applyCalendarDraft(result.calendar_draft);else $('calendar-event-status').textContent=result.text||'Draft unavailable. You can fill in the form manually.';
  }catch(error){if(calendarDraftRequest===controller&&eventDialog.open)$('calendar-event-status').textContent=error.name==='AbortError'?'Draft cancelled.':error.message;}
  finally{if(calendarDraftRequest===controller){calendarDraftRequest=null;resetDraftControls();}}
};
function resetDraftControls(){
  $('calendar-draft-build').disabled=false;$('calendar-event-fields').disabled=false;
  $('calendar-event-submit').disabled=!fresh('sources')||!(data.sources?.items||[]).some(i=>i.kind==='calendar'&&(editingEvent?i.entity_id===editingEvent.calendar&&i.editable:i.writable)&&i.available);
}
function closeEvent(){if($('calendar-event-submit').dataset.sending==='true')return;eventDialog.close();createButton.focus();}
eventDialog.addEventListener('close',()=>{calendarDraftRequest?.abort();calendarDraftRequest=null;resetDraftControls();});
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
    if(!editingEvent&&$('event-repeat').value)eventDraft.event.recurrence={frequency:$('event-repeat').value,interval:Number($('event-interval').value),count:Number($('event-count').value)};
    if(editingEvent)Object.assign(eventDraft,{operation:'edit',reference:editingEvent.reference,scope:editingScope});
  }
  button.dataset.sending='true';button.disabled=true;$('calendar-event-fields').disabled=true;$('calendar-event-status').textContent='Sending to your calendar…';
  $('calendar-draft-build').disabled=true;
  try{const result=await api(editingEvent?'/v1/display/calendar/change':'/v1/display/calendar/events',eventDraft);$('calendar-event-status').textContent=result.text;button.textContent=result.status==='accepted'?'Accepted':'Check your calendar';delete data.briefing;void refresh();}
  catch(error){
    if([403,409,422].includes(error.status)){eventDraft=null;$('calendar-event-fields').disabled=false;button.textContent=editingEvent?'Save changes':'Create event';$('calendar-event-status').textContent=error.message+' Review the fields and calendar permissions, then try again.';}
    else{$('calendar-event-status').textContent=error.message+' Check the agenda if the connection was lost. Retrying sends the same request identifier.';button.textContent='Retry same request';}
    button.disabled=false;$('calendar-draft-build').disabled=!!eventDraft;
  }
  finally{button.dataset.sending='false';}
};
const calendarDetails=document.createElement('dialog');calendarDetails.id='calendar-details-dialog';
calendarDetails.innerHTML='<div class="row spread"><h2 id="calendar-details-title"></h2><button class="icon-button" id="calendar-details-close" aria-label="Close event details" type="button">×</button></div><div id="calendar-details-content"></div><p id="calendar-details-status" class="tiny soft" role="status"></p><div class="row"><button class="pill" id="calendar-details-edit" type="button">Edit event</button><button class="pill" id="calendar-details-delete" type="button">Delete…</button><button class="pill" id="calendar-details-cancel" type="button" hidden>Keep event</button><button class="pill danger" id="calendar-details-confirm" type="button" hidden>Delete event</button></div>';
document.body.append(calendarDetails);
let detailedEvent=null,deleteDraft=null,deletingEvent=false,detailsAction=null;
const scopePanel=document.createElement('div');scopePanel.className='calendar-scope';scopePanel.hidden=true;
scopePanel.innerHTML='<label>Apply to<select id="calendar-change-scope"></select></label><p id="calendar-scope-note" class="tiny soft"></p>';
$('calendar-details-status').before(scopePanel);
const scopeNames={single:'This event',occurrence:'Only this occurrence',following:'This and following occurrences',series:'Every occurrence in the series'};
function scopesFor(item,operation){return item.change_scopes?.[operation]||(!item.recurring&&item.reference?['single']:[]);}
function showCalendarDetails(item){
  detailedEvent=item;deleteDraft=null;detailsAction=null;scopePanel.hidden=true;
  $('calendar-details-title').textContent=item.title;
  const firstDay=new Date(item.start.slice(0,10)+'T12:00:00'),lastDay=new Date(item.end.slice(0,10)+'T12:00:00');lastDay.setDate(lastDay.getDate()-1);
  const times=item.all_day?firstDay.toLocaleDateString(undefined,{weekday:'long',month:'long',day:'numeric'})+(localDate(lastDay)!==item.start?' → '+lastDay.toLocaleDateString():'')+' · All day':`${new Date(item.start).toLocaleString()} → ${new Date(item.end).toLocaleString()}`;
  $('calendar-details-content').innerHTML=`<p class="soft">${esc(item.calendar_name)}</p><p>${esc(times)}</p>${item.location?`<p>${esc(item.location)}</p>`:''}<p class="calendar-event-notes">${esc(item.description||'No notes.')}</p>${item.recurring?'<p class="soft">Repeating event · choose which occurrences a change affects.</p>':''}`;
  const source=data.sources?.items.find(s=>s.entity_id===item.calendar),valid=fresh('sources')&&source?.available&&item.reference;
  $('calendar-details-edit').hidden=!valid||!source.editable||!scopesFor(item,'edit').length;
  $('calendar-details-delete').hidden=!valid||!source.deletable||!scopesFor(item,'delete').length;
  $('calendar-details-confirm').hidden=$('calendar-details-cancel').hidden=true;
  $('calendar-details-confirm').disabled=$('calendar-details-edit').disabled=$('calendar-details-delete').disabled=false;
  $('calendar-details-confirm').textContent='Delete event';
  $('calendar-details-confirm').classList.add('danger');$('calendar-details-cancel').textContent='Keep event';
  $('calendar-details-status').textContent=valid&&(source.editable||source.deletable)?'Edits and deletion are enabled by the owner. The event is rechecked before a change.':'Read-only here. The owner can share supported calendar changes in Settings → Calendars & cameras.';
  calendarDetails.showModal();
}
function closeCalendarDetails(){if(!deletingEvent)calendarDetails.close();}
$('calendar-details-close').onclick=closeCalendarDetails;
calendarDetails.addEventListener('cancel',event=>{if(deletingEvent)event.preventDefault();});
function editCalendarDetails(scope='single'){
  const item=detailedEvent;calendarDetails.close();openCalendarEvent();editingEvent=item;editingScope=scope;
  draftComposer.hidden=true;recurrenceFields.hidden=true;eventDialog.querySelector('h2').textContent='Edit calendar event';
  $('event-calendar').innerHTML=`<option value="${esc(item.calendar)}">${esc(item.calendar_name)}</option>`;$('event-calendar').disabled=true;
  const zone=Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC';
  const local=iso=>{const d=new Date(iso);return `${localDate(d)}T${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;};
  applyCalendarDraft({event:{...item,timezone:zone,start:item.all_day?item.start:local(item.start),end:item.all_day?item.end:local(item.end)}});
  if(!item.all_day)for(const field of ['start','end'])$('event-'+field+'-fold').value=String(Math.abs(new Date($( 'event-'+field).value).getTime()-new Date(item[field]).getTime())>=3599000?1:0);
  $('calendar-event-status').textContent=scope==='single'?'Review your changes, then save. The event will stay in this calendar.':scopeNames[scope]+'. The existing repeat pattern stays unchanged. Review the dates and time zone before saving.';
  $('event-all-day').disabled=scope==='following';
  $('event-start').disabled=$('event-start-fold').disabled=scope==='following'&&item.following_start_locked!==false;
  if($('event-start').disabled)$('calendar-event-status').textContent='Following occurrences. Start is fixed here to preserve the remaining event count. You can change the title, notes, location and end time. Move one occurrence or use the calendar app to reschedule the series.';
  eventDialog.querySelector('h2').textContent=scope==='following'?'Edit following occurrences':scope==='occurrence'?'Edit this occurrence':'Edit calendar event';
  $('calendar-event-submit').textContent=scope==='following'?'Save following events':scope==='occurrence'?'Save this occurrence':'Save changes';resetDraftControls();
}
function chooseCalendarScope(operation){
  detailsAction=operation;deleteDraft=null;
  const scopes=scopesFor(detailedEvent,operation);
  $('calendar-change-scope').innerHTML=scopes.map(scope=>`<option value="${scope}">${scopeNames[scope]}</option>`).join('');
  $('calendar-change-scope').disabled=false;scopePanel.hidden=!detailedEvent.recurring;
  $('calendar-details-delete').hidden=$('calendar-details-edit').hidden=true;
  $('calendar-details-confirm').hidden=$('calendar-details-cancel').hidden=false;
  $('calendar-details-confirm').disabled=!scopes.length;
  $('calendar-details-cancel').textContent=operation==='edit'?'Cancel':'Keep event';
  $('calendar-details-confirm').classList.toggle('danger',operation==='delete');
  updateCalendarScope();
}
function updateCalendarScope(){
  const scope=$('calendar-change-scope').value;
  const edit=detailsAction==='edit';
  $('calendar-details-confirm').textContent=edit?'Continue to edit':scope==='series'?'Delete entire series':scope==='following'?'Delete following events':scope==='occurrence'?'Delete this occurrence':'Delete event';
  $('calendar-scope-note').textContent=scope==='following'?'Earlier occurrences stay unchanged. The selected occurrence is included.':scope==='series'?'Includes past and future occurrences, including changed exceptions.':'Other occurrences stay unchanged.';
  $('calendar-details-status').textContent=edit?'Next, review the fields before saving. The repeat pattern will stay unchanged.':scope==='series'?'Delete the entire series from its calendar? This affects everyone who uses the calendar.':scope==='following'?'Delete this occurrence and all following occurrences? Earlier events will remain.':scope==='occurrence'?'Delete only this occurrence? The rest of the series will remain.':'Delete this event from its calendar? This removes the event for everyone who uses that calendar.';
}
$('calendar-change-scope').onchange=updateCalendarScope;
$('calendar-details-edit').onclick=()=>{
  if(detailedEvent.recurring)chooseCalendarScope('edit');else editCalendarDetails();
};
$('calendar-details-delete').onclick=()=>chooseCalendarScope('delete');
$('calendar-details-cancel').onclick=()=>{calendarDetails.close();showCalendarDetails(detailedEvent);};
$('calendar-details-confirm').onclick=async()=>{
  if(deletingEvent)return;
  if(detailsAction==='edit')return editCalendarDetails($('calendar-change-scope').value);
  if(!deleteDraft)deleteDraft={operation:'delete',reference:detailedEvent.reference,scope:$('calendar-change-scope').value,revision:data.sources.revision,request_id:crypto.randomUUID().replaceAll('-','')};
  $('calendar-change-scope').disabled=true;
  deletingEvent=true;$('calendar-details-confirm').disabled=true;$('calendar-details-cancel').disabled=true;
  try{
    const result=await api('/v1/display/calendar/change',deleteDraft);
    $('calendar-details-status').textContent=result.text;$('calendar-details-confirm').textContent=result.status==='accepted'?'Accepted':'Check your calendar';
    $('calendar-details-cancel').hidden=true;delete data.briefing;void refresh();
  }catch(error){
    $('calendar-details-status').textContent=error.message;
    if([403,409,422].includes(error.status))$('calendar-details-status').textContent+=' Close this view and refresh the agenda before trying again.';
    else{$('calendar-details-confirm').disabled=false;$('calendar-details-confirm').textContent='Retry same request';$('calendar-details-status').textContent+=' If the connection was lost, check the calendar. Retrying uses the same request identifier.';}
  }finally{deletingEvent=false;$('calendar-details-cancel').disabled=false;}
};

'use strict';
document.querySelector('main').append($('planner-template').content.cloneNode(true));
titles.planner='Make room for your day.';
endpoints.schedules='/v1/schedules';
const weekdayNames=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
let editingSchedule=null, editingScheduleRevision=null, quietRevision=null;
const localZone=Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
$('schedule-zone').value=localZone; $('quiet-zone').value=localZone;
function localDate(date) { return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`; }
$('schedule-date').value=localDate(new Date());
$('schedule-days').innerHTML=weekdayNames.map((name,index)=>`<label><input type="checkbox" value="${index}"><span>${name}</span></label>`).join('');
function repeatFields() { const once=$('schedule-repeat').value==='once'; $('schedule-date-label').hidden=!once; $('schedule-date').required=once; $('schedule-days').hidden=$('schedule-repeat').value!=='custom'; }
$('schedule-repeat').onchange=repeatFields;
function resetSchedule() { editingSchedule=null; $('schedule-form').reset(); $('schedule-zone').value=localZone; $('schedule-date').value=localDate(new Date()); $('schedule-heading').textContent='Alarms & reminders'; repeatFields(); }
$('schedule-reset').onclick=resetSchedule;
function scheduleDescription(item) {
  const repeat=item.weekdays.length ? item.weekdays.map(i=>weekdayNames[i]).join(', ') : item.local_date;
  return `${item.time} · ${repeat} · ${item.timezone}`;
}
function scheduleRender() {
  const state=data.schedules;
  $('schedule-list').innerHTML=state?.items.length ? state.items.map(item=>`<div class="schedule-item"><div><strong>${esc(item.title)}</strong><p class="tiny soft">${esc(scheduleDescription(item))}<br>${item.enabled ? 'Next: '+esc(new Date(item.next_at*1000).toLocaleString()) : 'Disabled'}</p></div><div class="row"><button class="pill" data-schedule-edit="${item.id}" data-requires="schedules">Edit</button><button class="delete-button" data-schedule-delete="${item.id}" data-requires="schedules" aria-label="Delete ${esc(item.title)}">×</button></div></div>`).join('') : empty(state ? 'No scheduled alarms or reminders yet.' : 'Schedule service unavailable.');
  const events=(state?.events || []).filter(e=>e.status!=='dismissed').slice().reverse();
  $('schedule-events').innerHTML=events.length ? events.map(e=>`<div class="schedule-item"><strong>${esc(e.title)}</strong><p class="soft">${esc(e.message)}</p><span class="tiny soft">${esc(human(e.status))} · ${esc(new Date(e.due_at*1000).toLocaleString())}${e.delivered ? ' · Spoken' : ''}</span><div class="row">${['due','missed'].includes(e.status) ? `<button class="pill" data-event-snooze="${e.id}" data-requires="schedules">Snooze 5 min</button>` : ''}<button class="pill" data-event-dismiss="${e.id}" data-requires="schedules">Dismiss</button></div></div>`).join('') : empty('All quiet here.');
  $('quiet-status').textContent=state ? state.quiet_active ? 'Quiet hours active' : 'Outside quiet hours' : 'Unavailable';
  if (state && quietRevision!==state.revision && !$('quiet-form').contains(document.activeElement)) {
    const q=state.quiet; $('quiet-enabled').checked=q.enabled; $('quiet-start').value=q.start; $('quiet-end').value=q.end; $('quiet-zone').value=q.timezone; $('quiet-alarms').checked=q.alarms_override; quietRevision=state.revision;
  }
}
extensions.push(scheduleRender);
const notificationForm=document.createElement('form');notificationForm.className='card planner-notifications';
notificationForm.innerHTML='<span class="eyebrow">LEAVE A LITTLE NOTE</span><h2>Household message</h2><label>Title<input id="notice-title" maxlength="80" value="A note for home" required></label><label>Message<textarea id="notice-message" maxlength="400" rows="3" required></textarea></label><label class="check-label"><input id="notice-announce" type="checkbox">Also speak on the connected Echo audio endpoint</label><p class="tiny soft">Messages appear in Notifications. Spoken announcements respect quiet hours. This does not broadcast to other speakers.</p><button class="pill primary" type="submit" data-requires="schedules">Send message</button>';
$('page-planner').append(notificationForm);
notificationForm.onsubmit=event=>{event.preventDefault();action(async()=>{await api('/v1/notifications',{title:$('notice-title').value,message:$('notice-message').value,announce:$('notice-announce').checked});$('notice-message').value='';$('notice-announce').checked=false;},'Household message saved.');};
$('schedule-form').onsubmit=event=>{
  event.preventDefault(); if (!fresh('schedules')) return;
  const repeat=$('schedule-repeat').value;
  const weekdays=repeat==='daily' ? [0,1,2,3,4,5,6] : repeat==='weekdays' ? [0,1,2,3,4] : repeat==='custom' ? [...$('schedule-days').querySelectorAll('input:checked')].map(i=>Number(i.value)) : [];
  if (repeat==='custom' && !weekdays.length) return toast('Choose at least one weekday.');
  const schedule={title:$('schedule-title').value.trim(),kind:$('schedule-kind').value,message:$('schedule-message').value.trim(),time:$('schedule-time').value,timezone:$('schedule-zone').value.trim(),weekdays,local_date:repeat==='once' ? $('schedule-date').value : null,enabled:$('schedule-enabled').checked};
  action(async()=>{const result=await api('/v1/schedules'+(editingSchedule ? '/'+editingSchedule : ''),{revision:editingSchedule ? editingScheduleRevision : data.schedules.revision,schedule},editingSchedule ? 'PUT' : 'POST'); resetSchedule(); return result;},'Schedule saved.');
};
$('quiet-form').onsubmit=event=>{event.preventDefault(); if (!fresh('schedules')) return; const quiet={enabled:$('quiet-enabled').checked,start:$('quiet-start').value,end:$('quiet-end').value,timezone:$('quiet-zone').value.trim(),alarms_override:$('quiet-alarms').checked}; action(()=>api('/v1/schedule-preferences',{revision:quietRevision,quiet},'PUT'),'Quiet hours saved.');};
document.addEventListener('click',event=>{
  const button=event.target.closest('button'); if (!button || button.disabled || busy || !fresh('schedules')) return;
  if (button.dataset.scheduleEdit) {
    const item=data.schedules.items.find(i=>i.id===button.dataset.scheduleEdit); if (!item) return;
    editingSchedule=item.id; editingScheduleRevision=data.schedules.revision; $('schedule-heading').textContent='Edit schedule';
    for (const field of ['title','kind','message','time']) $('schedule-'+field).value=item[field];
    $('schedule-zone').value=item.timezone; $('schedule-enabled').checked=item.enabled; $('schedule-repeat').value=item.weekdays.length ? 'custom' : 'once';
    $('schedule-date').value=item.local_date || localDate(new Date());
    $('schedule-days').querySelectorAll('input').forEach(input=>input.checked=item.weekdays.includes(Number(input.value))); repeatFields(); $('schedule-title').focus();
  }
  if (button.dataset.scheduleDelete) action(()=>api('/v1/schedules/'+button.dataset.scheduleDelete,{revision:data.schedules.revision},'DELETE'),'Schedule removed.');
  if (button.dataset.eventSnooze || button.dataset.eventDismiss) action(()=>api('/v1/schedule-events/'+(button.dataset.eventSnooze || button.dataset.eventDismiss),{action:button.dataset.eventSnooze ? 'snooze' : 'dismiss',minutes:5}),button.dataset.eventSnooze ? 'Snoozed for five minutes.' : 'Notification dismissed.');
});

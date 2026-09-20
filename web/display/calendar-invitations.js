'use strict';
/* Guest edits use their own read/review/confirm path; no credentials or drafts are persisted. */
const calendarInvitationControls=(()=>{
  const dialog=document.createElement('dialog');dialog.id='calendar-invitations-dialog';
  dialog.innerHTML=`<form id="calendar-invitations-form"><div class="row spread"><div><span class="eyebrow">GOOGLE CALENDAR GUESTS</span><h2 id="calendar-invitations-title">Review guests</h2></div><button id="calendar-invitations-close" class="icon-button" type="button" aria-label="Close guest review">×</button></div><div class="calendar-invitations-scroll"><p id="calendar-invitations-event" class="soft"></p><fieldset id="calendar-invitations-fields" disabled><h3>Current guests</h3><p class="tiny soft">Existing guests stay unless you select Remove. Response status and other existing guest details are preserved.</p><div id="calendar-invitations-guests"></div><label>Add guests<textarea id="calendar-invitations-add" rows="2" maxlength="20000" placeholder="Email addresses, separated by commas or new lines"></textarea></label><label>Google notifications<select id="calendar-invitations-notifications" required><option value="">Choose notifications</option><option value="all">All guests</option><option value="externalOnly">Only guests who do not use Google Calendar</option><option value="none">Request no notifications</option></select></label><p id="calendar-invitations-effect" class="tiny soft"></p></fieldset><section id="calendar-invitations-review" hidden><h3>Review this change</h3><div id="calendar-invitations-changes"></div><p id="calendar-invitations-review-effect"></p><p class="tiny soft">Google controls notification delivery and guest calendar synchronization. Resource guests may also affect room or equipment bookings. This review expires in five minutes or sooner.</p><label class="check-label"><input id="calendar-invitations-ack" type="checkbox">I reviewed the guest changes and notification choice.</label></section></div><p id="calendar-invitations-status" class="tiny soft" role="status"></p><div class="row calendar-invitations-actions"><button id="calendar-invitations-back" class="pill" type="button" hidden>Change selection</button><button id="calendar-invitations-cancel" class="pill" type="button">Close</button><button id="calendar-invitations-submit" class="pill primary" type="submit" disabled>Review guest changes</button></div></form>`;
  document.body.append(dialog);
  const el=id=>document.getElementById('calendar-invitations-'+id);
  dialog.querySelector('.calendar-invitations-scroll').before(el('event'));
  let active=null,sequence=0;
  const identity=()=>JSON.stringify([data.session?.receiver_id||'owner',data.session?.role,data.session?.profile_revision||0,data.session?.member?.id||null]);
  const permitted=()=>!!data.session&&!data.session.member&&data.session.profile?.mode!=='guest'&&!signInRequired;
  function current(state){
    const valid=active===state&&dialog.open&&state.identity===identity()&&permitted()&&state.revision===data.sources?.revision;
    if(!valid&&active===state)clear();
    return valid;
  }
  function clear(){sequence++;active?.controller?.abort();active=null;if(dialog.open)dialog.close();el('guests').replaceChildren();el('changes').replaceChildren();el('add').value='';el('ack').checked=false;}
  function close(){if(active?.sending)return;clear();}
  function line(parent,text,className){const p=document.createElement('p');p.textContent=text;if(className)p.className=className;parent.append(p);return p;}
  function showGuests(guests){
    el('guests').replaceChildren();
    if(!guests.length)line(el('guests'),'No current guests.','soft');
    for(const guest of guests){
      const row=document.createElement('div');row.className='calendar-invitations-guest';
      const info=document.createElement('div');line(info,guest.display_name?guest.display_name+' · '+guest.email:guest.email);
      line(info,[guest.response_status,guest.optional?'Optional':'',guest.resource?'Resource':'',guest.protected?'Organizer or this account':''].filter(Boolean).join(' · '),'tiny soft');row.append(info);
      if(!guest.protected){const label=document.createElement('label');label.className='check-label';const input=document.createElement('input');input.type='checkbox';input.dataset.removeEmail=guest.email;label.append(input,document.createTextNode('Remove'));row.append(label);}
      el('guests').append(row);
    }
  }
  function showReview(result){
    el('changes').replaceChildren();
    for(const [label,values] of [['Add',result.added],['Remove',result.removed],['Keep',result.attendees.filter(a=>!result.added.includes(a.email)).map(a=>a.email)]]){
      const block=document.createElement('div');block.className='calendar-invitations-change';
      const title=document.createElement('strong');title.textContent=label+' ('+values.length+')';block.append(title);
      const list=document.createElement('ul');for(const email of values){const li=document.createElement('li');li.textContent=email;list.append(li);}block.append(list);el('changes').append(block);
    }
    el('review-effect').textContent=result.notification_effect;
    el('fields').hidden=true;el('review').hidden=false;el('back').hidden=false;el('ack').checked=false;
    el('submit').textContent='Confirm guest changes';el('submit').disabled=true;
    el('title').textContent='Confirm guests & notifications';el('status').textContent='Nothing has been sent. Confirm only after reviewing every change above.';
    el('review').scrollIntoView({block:'start'});
  }
  async function open(item,options={}){
    clear();
    if(!permitted()||!item.invitation_reference||!Number.isInteger(options.revision))return;
    const state={identity:identity(),revision:options.revision,item,options,controller:new AbortController(),id:++sequence,read:null,review:null,confirmation:null,sending:false};active=state;
    el('form').reset();el('ack').disabled=false;el('fields').hidden=false;el('fields').disabled=true;el('review').hidden=true;el('back').hidden=true;
    el('submit').textContent='Review guest changes';el('submit').disabled=true;el('close').disabled=el('cancel').disabled=false;
    el('title').textContent='Review guests';el('effect').textContent='Choose how Google should notify guests. No option is selected automatically.';
    el('event').textContent=item.title||'Calendar event';el('status').textContent='Loading the complete guest list…';dialog.showModal();
    try{
      const result=await api('/v1/display/calendar/invitations/read',{reference:item.invitation_reference,revision:options.revision},'POST',state.controller.signal);
      if(!current(state))return;
      state.read=result;showGuests(result.attendees);el('fields').disabled=false;el('submit').disabled=false;
      const allDay=!!result.event.start.date;
      const formatted=value=>allDay?new Date(value+'T12:00:00').toLocaleDateString():new Date(value).toLocaleString([],{dateStyle:'medium',timeStyle:'short'});
      const start=formatted(result.event.start.dateTime||result.event.start.date),end=formatted(result.event.end.dateTime||result.event.end.date);
      el('event').textContent=result.event.title+' · '+start+(allDay?' · All day, ends before ':' → ')+end+' · '+(result.event.scope==='occurrence'?'Only this occurrence':'This event');
      el('status').textContent='Select guest changes and a notification choice, then review. Nothing is sent while editing.';
    }catch(error){if(current(state))el('status').textContent=error.message;}
  }
  el('notifications').onchange=()=>{el('effect').textContent=active?.read?.notification_choices[el('notifications').value]||'Choose how Google should notify guests.';};
  el('ack').onchange=()=>{el('submit').disabled=!el('ack').checked||!!active?.sending;};
  el('back').onclick=()=>{
    if(!active||active.sending||active.confirmation)return;
    active.review=null;el('fields').hidden=false;el('fields').disabled=false;el('review').hidden=true;el('back').hidden=true;
    el('submit').disabled=false;el('submit').textContent='Review guest changes';el('title').textContent='Review guests';el('status').textContent='Review the revised selection before confirming.';
  };
  el('close').onclick=el('cancel').onclick=close;
  dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
  dialog.addEventListener('close',()=>{if(active&&!dialog.open)clear();});
  el('form').onsubmit=async event=>{
    event.preventDefault();const state=active;if(!state||!current(state)||state.sending||!state.read)return;
    if(!state.review){
      state.sending=true;el('fields').disabled=true;el('submit').disabled=true;el('close').disabled=el('cancel').disabled=true;el('status').textContent='Checking the event and preparing your review…';
      try{
        const result=await api('/v1/display/calendar/invitations/review',{read_id:state.read.read_id,add:el('add').value.split(/[,\n]+/).map(s=>s.trim()).filter(Boolean),
          remove:[...el('guests').querySelectorAll('input:checked')].map(input=>input.dataset.removeEmail),send_updates:el('notifications').value},'POST',state.controller.signal);
        if(!current(state))return;state.review=result;showReview(result);
      }catch(error){if(current(state)){el('status').textContent=error.message;el('fields').disabled=false;el('submit').disabled=false;}}
      finally{if(current(state)){state.sending=false;el('close').disabled=el('cancel').disabled=false;}}
      return;
    }
    if(!el('ack').checked)return;
    if(!state.confirmation){
      if(state.review.expires_at*1000<=Date.now()){el('status').textContent='This review expired. Close and open the event again.';el('submit').disabled=true;return;}
      state.confirmation=Object.fromEntries(['review_id','review_proof','request_id','reference','revision'].map(k=>[k,state.review[k]]));state.confirmation.confirmed=true;
    }
    state.sending=true;el('submit').disabled=true;el('back').hidden=true;el('ack').disabled=true;el('close').disabled=el('cancel').disabled=true;
    el('status').textContent='Submitting the confirmed guest and notification choice…';
    try{
      const result=await api('/v1/display/calendar/invitations/confirm',state.confirmation,'POST',state.controller.signal);
      if(!current(state))return;
      el('status').textContent=result.text;el('submit').textContent=result.status==='accepted'?'Accepted':'Check Google Calendar';
      state.options.onComplete?.(result);
    }catch(error){
      if(!current(state))return;
      el('status').textContent=error.message;
      if([401,403,409,422].includes(error.status))el('status').textContent+=' Close this review and refresh the agenda before continuing.';
      else{el('status').textContent+=' Check Google Calendar if the connection was lost. Retrying uses exactly the same reviewed request.';el('submit').textContent='Retry same request';el('submit').disabled=false;}
    }finally{if(current(state)){state.sending=false;el('close').disabled=el('cancel').disabled=false;}}
  };
  extensions.push(()=>{if(active&&!current(active))clear();});
  window.addEventListener('hashchange',clear);
  document.addEventListener('echo:page',event=>{if(event.detail!=='day')clear();});
  return {open,cancel:clear};
})();
function openCalendarInvitations(item,options){return calendarInvitationControls.open(item,options);}
function cancelCalendarInvitations(){calendarInvitationControls.cancel();}

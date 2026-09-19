/* Native Pi chimes continue when the page reloads. The browser owns no alarm sound. */
'use strict';
endpoints.alertSettings='/v1/display/alert-settings';
const alertCard=document.createElement('article');alertCard.className='card';alertCard.style.marginTop='16px';
alertCard.innerHTML='<span class="eyebrow">THIS DEVICE</span><h2>Alarms on this Pi.</h2><p id="pi-alert-status" class="soft">Checking the attached audio adapter…</p><form id="pi-alert-form" hidden><label>Attached speaker / audio output<select id="pi-alert-output" required></select></label><label>Chime volume <output id="pi-alert-level">2%</output><input type="range" id="pi-alert-volume" min="0" max="30" value="2"></label><label class="check-label"><input type="checkbox" id="pi-alert-enabled">Enable timer and reminder chimes</label><button class="pill primary" type="submit">Save alerts</button><p class="tiny soft">A soft chime plays through this Pi; the message stays on screen. Music pauses first. During a call or recording, sound waits. Dismiss or snooze an alert here or on Planner. Sound needs the host connection and a working speaker.</p></form>';
$('page-settings').append(alertCard);
const alertBanner=document.createElement('aside');alertBanner.id='pi-alert-banner';alertBanner.className='pi-alert-banner';alertBanner.hidden=true;alertBanner.setAttribute('aria-live','polite');document.body.append(alertBanner);
let alertSignature='',visibleAlert=null;
extensions.push(()=>{
  const state=data.alertSettings,supported=!!state?.supported;
  $('pi-alert-form').hidden=!supported;
  $('pi-alert-status').textContent=!fresh('alertSettings')?'Local alert adapter unavailable.':!supported?'Configure Pi chimes from its installed display bridge.':state.error||(!state.settings.enabled?'Chimes are off. Timers remain visible.':!state.settings.volume?'Chime volume is zero. Timers remain visible.':'Chimes enabled on the attached Pi speaker.');
  if(supported)endpoints.displayAlerts='/v1/display/alerts';
  const signature=JSON.stringify([state?.settings,state?.outputs]);
  if(supported&&signature!==alertSignature&&!$('pi-alert-form').contains(document.activeElement)){
    alertSignature=signature;const settings=state.settings,items=state.outputs||[];
    $('pi-alert-enabled').checked=settings.enabled;$('pi-alert-volume').value=settings.volume;$('pi-alert-level').textContent=settings.volume+'%';
    $('pi-alert-output').innerHTML='<option value="">Choose an attached output</option>'+items.map(o=>`<option value="${esc(o.id)}">${esc(o.name)} · ${esc(o.id)}</option>`).join('');
    if(settings.output&&!items.some(o=>o.id===settings.output))$('pi-alert-output').insertAdjacentHTML('beforeend',`<option value="${esc(settings.output)}">${esc(settings.output)} · unavailable</option>`);
    $('pi-alert-output').value=settings.output;
  }
  visibleAlert=fresh('displayAlerts')?(data.displayAlerts?.items||[]).find(i=>i.finished):null;
  alertBanner.hidden=!visibleAlert;
  if(visibleAlert){const item=visibleAlert;const text=`<div><span class="eyebrow">${esc(human(item.kind||'timer'))} READY</span><strong>${esc(item.label)}</strong>${item.spoken_text?`<p>${esc(item.spoken_text)}</p>`:''}<span class="tiny soft">${(item.delivered??item.notified)?'Chime delivered':state?.settings.enabled?'Sound waits for an available speaker and quiet-hour settings.':'Chimes are off; enable them in Settings.'}</span></div><div class="row"><button class="pill" data-alert-action="snooze">Snooze 5 min</button><button class="pill primary" data-alert-action="dismiss">Dismiss</button></div>`;if(alertBanner.innerHTML!==text)alertBanner.innerHTML=text;}
});
$('pi-alert-volume').oninput=()=>{$('pi-alert-level').textContent=$('pi-alert-volume').value+'%';};
$('pi-alert-form').onsubmit=event=>{event.preventDefault();void action(()=>api('/v1/display/alert-settings',{enabled:$('pi-alert-enabled').checked,output:$('pi-alert-output').value,volume:Number($('pi-alert-volume').value)},'PUT'),'Pi alert settings saved.');};
alertBanner.onclick=event=>{const button=event.target.closest('[data-alert-action]'),item=visibleAlert;if(!button||!item)return;const command=button.dataset.alertAction;void action(()=>item.kind?api('/v1/schedule-events/'+item.id,{action:command,minutes:5}):command==='snooze'?api('/v1/timers/'+item.id+'/snooze',{}):api('/v1/timers/'+item.id,{},'DELETE'),command==='snooze'?'Snoozed for five minutes.':'Alert dismissed.');};

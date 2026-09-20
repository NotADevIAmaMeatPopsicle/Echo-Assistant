/* Echo's large display. Credentials and conversation content never enter localStorage. */
'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icon = name => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const empty = text => `<p class="empty">${esc(text)}</p>`;
const human = value => String(value || 'unavailable').replaceAll('_', ' ');
const data = {}, received = {};
const extensions = [];
const pageEndpoints = {};
let busy = false, polling = false, voicePolling = false, displayCaptureBusy = false, signInRequired = false, kind = 'shopping', chatAbort, lastInput = Date.now(), photos = [], photoIndex = 0, previousFocus;
let preferences = {clock24:false, idle:300, dim:false};
try { const saved = JSON.parse(localStorage.getItem('echo-display-preferences') || '{}');
  preferences = {clock24:saved.clock24 === true, idle:[0,60,300,900].includes(saved.idle) ? saved.idle : 300, dim:saved.dim === true};
} catch { /* Browser storage is optional. */ }
const titles = {home:'Your day, a little easier.', rooms:'A home that listens.', music:'Set the mood.', timers:'Time, on your side.', lists:'One less thing to remember.', routines:'Make it a ritual.', assistant:'A little help from Echo.', settings:'Make it yours.'};
const fresh = key => data[key] && Date.now() - (received[key] || 0) < 20000;
function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(() => $('toast').hidden = true, 6500); }
async function api(path, body, method = 'POST', signal) {
  const response = await fetch(path, {method:body === undefined ? 'GET' : method, credentials:'same-origin',
    headers:{...(body === undefined ? {} : {'Content-Type':'application/json','X-Echo-Request':'1'}),...(data.session?{'X-Echo-Profile-Revision':String(data.session.profile_revision||0)}:{})}, body:body === undefined ? undefined : JSON.stringify(body),
    signal:signal || AbortSignal.timeout(10000), cache:'no-store'});
  let result; try { result = await response.json(); } catch { throw new Error('Echo returned an unreadable response.'); }
  if (!response.ok) {
    if (response.status === 401 && path!=='/v1/member/session' && !data.session?.member) { signInRequired = true; window.EchoVideo?.reset(); $('notice').textContent = response.headers.get('X-Echo-Display-Bridge')==='1' ? 'This display needs pairing again. Open Displays in the owner’s Echo settings to create a new pairing code.' : 'Sign in through the Echo launcher, then open Display. This screen needs an active Echo session.'; $('notice').hidden = false; }
    const error=new Error(response.status === 401 && path!=='/v1/member/session' && !data.session?.member ? 'Echo sign-in required.' : typeof result.detail === 'string' ? result.detail : `The request was not accepted (${response.status}).`);error.status=response.status;throw error;
  }
  if (path === '/v1/state') signInRequired = false;
  return result;
}
function page(name) {
  if(window.echoAllowedPages&&!window.echoAllowedPages.has(name))name='home';
  if (!titles[name]) name = 'home';
  document.querySelectorAll('.page').forEach(p => p.hidden = p.id !== `page-${name}`);
  document.querySelectorAll('[data-page]').forEach(b => { b.classList.toggle('selected', b.dataset.page === name); if (b.closest('nav') || b.classList.contains('rail-settings')) b.setAttribute('aria-current', b.dataset.page === name ? 'page' : 'false'); });
  $('page-title').textContent = titles[name]; history.replaceState(null, '', `${location.pathname}#${name}`);
  document.querySelector('main').scrollTop = 0;
  document.dispatchEvent(new CustomEvent('echo:page',{detail:name}));
  refresh();
}
function guardButtons() {
  document.querySelectorAll('[data-requires]').forEach(button => {
    button.disabled = busy || !fresh(button.dataset.requires) || button.dataset.unavailable === 'true';
  });
  for (const [form, source] of [['timer-form','timers'],['alarm-form','timers'],['list-form','household']]) {
    $(form).querySelector('button[type="submit"]').disabled = busy || !fresh(source);
  }
  document.querySelectorAll('[data-minutes]').forEach(b => b.disabled = busy || !fresh('timers'));
  $('send-chat').disabled = !!chatAbort || displayCaptureBusy || !fresh('timers') || signInRequired || (data.session?.profile?.mode==='guest'&&!data.session.profile.conversation);
}
async function action(callback, message = 'Command accepted. Checking the current state…') {
  if (busy) return; busy = true; guardButtons();
  try { const result = await callback(); toast(result?.text || message); }
  catch (error) { toast(error.name === 'TimeoutError' ? 'The request timed out. Check the current state before trying again.' : error.message); }
  finally { busy = false; await refresh(); guardButtons(); }
}
const endpoints = {health:'/health', home:'/v1/home', timers:'/v1/state', household:'/v1/household', routines:'/v1/routines'};
async function refreshVoice() {
  if (voicePolling) return; voicePolling = true;
  try {
    await Promise.allSettled([
      (async()=>{try {data.voice=await api('/v1/voice',undefined,'GET',AbortSignal.timeout(3000));received.voice=Date.now();}catch{delete data.voice;delete received.voice;}})(),
      (async()=>{if($('page-music').hidden && !(typeof homeShowsMusic==='function' && homeShowsMusic()))return;const path=typeof musicSnapshotPath==='function'?musicSnapshotPath():'/v1/display/music/now-playing';try {const value=await api(path,undefined,'GET',AbortSignal.timeout(5000));if(path!==musicSnapshotPath())return;data.nowPlaying=value;received.nowPlaying=Date.now();}catch{if(path===musicSnapshotPath()){delete data.nowPlaying;delete received.nowPlaying;}}})()
    ]);
  }
  catch { delete data.voice; delete received.voice; }
  finally { voicePolling = false; renderConnection(); renderVoice(); renderMusic(); guardButtons(); }
}
async function refresh() {
  if (polling) return; polling = true;
  try {
    await Promise.allSettled([refreshVoice(), ...Object.entries(endpoints).map(async ([key, url]) => {
      if (pageEndpoints[key] && $('page-'+pageEndpoints[key]).hidden) return;
      try { data[key] = await api(url); received[key] = Date.now(); }
      catch { delete data[key]; delete received[key]; }
    })]);
    render();
  } finally { polling = false; }
}
function renderConnection() {
  // A responding voice service can still be waiting for the separate speaker.
  // Use an authenticated core request to describe this display's connection.
  const online = fresh('timers') && !signInRequired, demo = data.health?.display_demo;
  $('connection').textContent = demo ? 'Demo · sample home' : signInRequired ? 'Pairing / sign-in needed' : online ? 'Display connected' : 'Host unreachable · retrying';
  $('connection').classList.toggle('live', !!online);
  $('connection').title = online ? 'This display can reach your Echo server.' : 'Checking this display’s connection to your Echo server.';
  if (online) { $('notice').hidden = true; $('last-update').textContent = demo ? 'Synthetic data · no devices connected' : 'Live state just refreshed'; }
  else { $('last-update').textContent = 'Live state unavailable · controls paused'; }
  $('privacy-status').textContent = demo ? 'Local preview · no sound or home actions' : 'Your Echo host · Your choice of assistant';
}
function render() {
  const demo = data.health?.display_demo;
  renderConnection();
  renderVoice(); renderHome(); renderMusic(); renderTimers(); renderLists(); renderRoutines(); guardButtons();
  extensions.forEach(renderExtension => renderExtension()); guardButtons();
  $('capability-notes').innerHTML = [['Echo server', fresh('timers') && !signInRequired ? 'connected' : 'unavailable'], ['Optional round speaker', roundSpeakerConnected() ? human(data.voice.status) : 'not connected'], ['Home Assistant', human(data.home?.status)], ['Lists', data.household?.storage === 'encrypted' ? 'encrypted on host' : demo ? 'demo session only' : 'session only'], ['Voice and audio', 'This device’s microphone and speakers'], ['Spotify on this display', 'Configure the Pi receiver below; other receivers are optional']].map(([name,value]) => `<div class="capability-row"><span>${esc(name)}</span><strong>${esc(value)}</strong></div>`).join('');
}
function roundSpeakerConnected() { return fresh('voice') && ['armed','activation','listening','thinking','speaking','music','alarm','cooldown','muted','intercom'].includes(data.voice.status); }
function renderVoice() {
  // Each display owns its capture/reply state; another endpoint is optional.
  document.dispatchEvent(new Event('echo:voice-state'));
}
function renderHome() {
  const home = data.home || {}, rooms = home.lights?.rooms || [], thermostat = home.devices?.thermostat, weather = home.devices?.weather;
  $('home-rooms').innerHTML = rooms.length ? rooms.map(r => `<button class="mini-room ${r.state === 'on' || r.state === 'mixed' ? 'on' : ''}" data-page="rooms">${icon('light')}<strong>${esc(r.name)}</strong><span>${esc(human(r.state))}</span></button>`).join('') : empty('Connect and assign rooms in Devices.');
  $('room-cards').innerHTML = rooms.length ? rooms.map(r => `<article class="card room-card"><div class="row spread">${icon('light')}<span class="tiny soft">${esc(human(r.state))}</span></div><h2>${esc(r.name)}</h2><p class="soft tiny">${Number(r.count) || 0} lights · ${r.available ? 'Available' : 'Unavailable'}</p><div class="room-buttons">${['turn_on','turn_off'].map(a => `<button data-room="${esc(r.id)}" data-room-action="${a}" data-requires="home" data-unavailable="${!r.available || !home.lights.revision}" class="${r.state === a.slice(5) ? 'active' : ''}">${a === 'turn_on' ? 'On' : 'Off'}</button>`).join('')}</div></article>`).join('') : empty('No room controls available. Assign devices in Echo’s Devices workspace.');
  const wa = weather?.attributes || {};
  $('weather-temperature').textContent = weather?.status === 'available' && Number.isFinite(wa.temperature) ? `${wa.temperature}${wa.temperature_unit || '°'}` : '—';
  $('weather-condition').textContent = weather?.status === 'available' ? human(weather.state) : 'Weather not connected';
  $('weather-detail').textContent = weather?.status === 'available' ? `${Number.isFinite(wa.humidity) ? `Humidity ${wa.humidity}% · ` : ''}From Home Assistant` : 'Connect a weather entity in Home Assistant.';
  $('ambient-weather').textContent = weather?.status === 'available' ? `${$('weather-temperature').textContent} · ${human(weather.state)}` : '';
  const ta = thermostat?.attributes || {}, unit = ta.temperature_unit;
  const canAdjust = thermostat?.status === 'available' && ['°C','°F'].includes(unit) && Number.isFinite(ta.temperature) && thermostat.state !== 'heat_cool';
  $('thermostat').innerHTML = `<span class="eyebrow">THERMOSTAT</span><div class="row spread"><div><div class="device-temperature">${Number.isFinite(ta.current_temperature) ? esc(ta.current_temperature) + esc(unit || '°') : '—'}</div><span class="soft">${esc(human(thermostat?.state))}</span></div><div class="stepper"><button aria-label="Lower target temperature" data-temp="-1" data-requires="home" data-unavailable="${!canAdjust}">−</button><strong>${Number.isFinite(ta.temperature) ? esc(ta.temperature) + esc(unit || '°') : '—'}</strong><button aria-label="Raise target temperature" data-temp="1" data-requires="home" data-unavailable="${!canAdjust}">+</button></div></div><p class="device-note">${canAdjust ? 'Target temperature · bounds checked by Home Assistant' : 'Temperature controls require an available, supported thermostat.'}</p>`;
  if (!$('speaker').contains(document.activeElement)) {
    const speakers = home.speakers || {}, attrs = speakers.device?.attributes || {}, available = speakers.device?.status === 'available' && !!speakers.binding;
    $('speaker').innerHTML = `<span class="eyebrow">HOME SPEAKER</span><label>Play through<select id="speaker-choice" data-requires="home" data-unavailable="${!speakers.choices?.length}">${(speakers.choices || []).map((choice,index) => `<option value="${index}" ${speakers.selected === index ? 'selected' : ''}>${esc(choice.name || choice.label || `Speaker ${index + 1}`)}</option>`).join('') || '<option>No speakers assigned</option>'}</select></label><div class="row spread"><span class="soft">${Number.isFinite(attrs.volume_level) ? Math.round(attrs.volume_level * 100) + '%' : 'Volume unavailable'}</span><div class="stepper">${[['down','−'],['up','+'],[attrs.is_volume_muted ? 'unmute' : 'mute',attrs.is_volume_muted ? 'Unmute' : 'Mute']].map(([command,label]) => `<button data-speaker="${command}" data-requires="home" data-unavailable="${!available}" aria-label="${command === 'up' ? 'Raise speaker volume' : command === 'down' ? 'Lower speaker volume' : label}">${label}</button>`).join('')}</div></div><p class="device-note">${esc(human(speakers.device?.state))} · Home Assistant speaker controls</p>`;
  }
}
function renderMusic() { if (typeof renderMusicPanel==='function') renderMusicPanel(); if (typeof renderHomeMusic==='function') renderHomeMusic(); }

function remaining(timer) { return Math.max(0, Math.ceil(timer.remaining_seconds - (Date.now() - received.timers) / 1000)); }
function duration(seconds) { return `${Math.floor(seconds / 3600) ? `${Math.floor(seconds / 3600)}:` : ''}${String(Math.floor(seconds / 60) % 60).padStart(2,'0')}:${String(seconds % 60).padStart(2,'0')}`; }
function renderTimers() {
  const timers = data.timers?.timers || [];
  $('timer-list').innerHTML = timers.length ? timers.map(t => `<div class="timer-item"><div><strong>${esc(t.label)}</strong><span class="soft">${fresh('timers') ? duration(remaining(t)) : 'State unavailable'}${t.finished ? ' · Finished' : ''}</span></div><button class="pill" data-dismiss="${esc(t.id)}" data-requires="timers">${t.finished ? 'Dismiss' : 'Cancel'}</button></div>`).join('') : empty('Nothing counting down. Make a little time.');
  const next = [...timers].sort((a,b) => a.remaining_seconds - b.remaining_seconds)[0];
  $('next-timer').innerHTML = next ? `<h2>${esc(next.label)}</h2><div class="timer-count">${fresh('timers') ? duration(remaining(next)) : '—'}</div>` : '<h2>No rush.</h2><p class="soft">Your next timer will appear here.</p>';
}
function renderLists() {
  const document = data.household;
  $('list-storage').textContent = document?.storage === 'encrypted' ? 'Encrypted on your host' : document ? 'This demo session only' : 'Lists unavailable';
  const items = (document?.items || []).filter(item => item.kind === kind);
  $('household-items').innerHTML = items.length ? items.map(item => `<div class="household-item ${item.done ? 'done' : ''}">${kind !== 'notes' ? `<button class="check-button ${item.done ? 'checked' : ''}" data-check="${item.id}" aria-label="${item.done ? 'Mark incomplete' : 'Mark complete'}: ${esc(item.text)}" data-requires="household">${item.done ? icon('check') : ''}</button>` : icon('list')}<span class="item-text">${esc(item.text)}</span><button class="delete-button" data-delete="${item.id}" aria-label="Delete: ${esc(item.text)}" data-requires="household">×</button></div>`).join('') : empty(document ? 'A little space for what’s next.' : 'Reconnect to view and edit your saved lists.');
}
function renderRoutines() {
  const items = data.routines?.items || [];
  $('routine-cards').innerHTML = items.length ? items.map(item => `<article class="card routine-card">${icon('routine')}<h2>${esc(item.name)}</h2><p class="soft">${item.steps?.length || 0} saved actions</p><button class="pill" data-routine="${esc(item.id)}" data-requires="routines">Review & run ↗</button></article>`).join('') : empty('Create a routine in Echo’s Routines workspace. It will appear here.');
}
async function newTimer(seconds, label) { return api('/v1/timers', {seconds, label}); }
document.addEventListener('click', event => {
  const button = event.target.closest('button, a.brand'); if (!button || button.disabled) return;
  if (button.classList.contains('brand')) { event.preventDefault(); page('home'); }
  if (button.dataset.page) page(button.dataset.page);
  if (button.dataset.requires && (!fresh(button.dataset.requires) || busy)) return;
  if (button.dataset.room) action(() => api(`/v1/home/rooms/${encodeURIComponent(button.dataset.room)}/actions`, {action:button.dataset.roomAction, revision:data.home.lights.revision}));
  if (button.dataset.temp) action(() => api('/v1/home/thermostat/actions', {action:'adjust_temperature', value:Number(button.dataset.temp), unit:data.home.devices.thermostat.attributes.temperature_unit}));
  if (button.dataset.speaker) action(() => api('/v1/home/speakers/control', {action:button.dataset.speaker, binding:data.home.speakers.binding}));
  if (button.dataset.minutes && fresh('timers')) action(() => newTimer(Number(button.dataset.minutes) * 60, `${button.dataset.minutes} minute timer`), 'Timer started.');
  if (button.dataset.dismiss) action(() => api(`/v1/timers/${encodeURIComponent(button.dataset.dismiss)}`, {}, 'DELETE'), 'Timer removed.');
  if (button.dataset.kind) { kind = button.dataset.kind; document.querySelectorAll('[data-kind]').forEach(b => b.classList.toggle('selected',b === button)); $('list-text').placeholder = {shopping:'Something to pick up…',tasks:'One thing to do…',notes:'Something worth keeping…'}[kind]; renderLists(); if (typeof enhanceLists==='function') enhanceLists(); guardButtons(); }
  if (button.dataset.check || button.dataset.delete) {
    const id = button.dataset.check || button.dataset.delete, item = data.household.items.find(i => i.id === id);
    if (item) action(() => api(`/v1/household/${id}`, {revision:data.household.revision, ...(button.dataset.check ? {done:!item.done} : {})}, button.dataset.check ? 'PATCH' : 'DELETE'), 'List saved.');
  }
  if (button.dataset.routine) {
    const item = data.routines.items.find(i => i.id === button.dataset.routine); if (!item) return;
    const dialog = $('confirm-routine'); $('confirm-title').textContent = `Run ${item.name}?`;
    $('confirm-description').textContent = item.steps.map(s => `${human(s.action)} · ${s.entity_id}${s.value != null ? ` · ${s.value}${s.unit || ''}` : ''}`).join('\n');
    dialog.returnValue = ''; dialog.onclose = () => { if (dialog.returnValue === 'run') action(() => api(`/v1/routines/${item.id}/run`, {revision:item.revision})); }; dialog.showModal();
  }
  if (button.dataset.prompt) { $('chat-text').value = button.dataset.prompt; $('chat-text').focus(); }
});
$('speaker').addEventListener('change', event => { if (event.target.id === 'speaker-choice' && fresh('home')) action(() => api('/v1/home/speakers/select', {index:Number(event.target.value),revision:data.home.speakers.revision}), 'Speaker selected.'); });
for (const [id, command] of [['play-track','toggle'],['previous-track','previous'],['next-track','next']]) $(id).onclick = () => { if (typeof sendMusic==='function') sendMusic(command); };
$('timer-form').onsubmit = event => { event.preventDefault(); if (fresh('timers')) action(() => newTimer(Number($('timer-minutes').value) * 60, $('timer-label').value.trim() || 'Timer'), 'Timer started.'); };
$('alarm-form').onsubmit = event => {
  event.preventDefault(); if (!fresh('timers')) return;
  const [hour, minute] = $('alarm-time').value.split(':').map(Number), now = new Date(), target = new Date();
  target.setHours(hour,minute,0,0); if (target <= now) target.setDate(target.getDate() + 1);
  const seconds = Math.ceil((target - now) / 1000);
  if (!(seconds >= 1 && seconds <= 86400)) return toast('Choose a time within the next 24 hours.');
  action(() => newTimer(seconds, `Alarm · ${target.toLocaleTimeString([], {hour:'numeric',minute:'2-digit',hour12:!preferences.clock24})}`), 'One-off alarm set.');
};
$('list-form').onsubmit = event => { event.preventDefault(); if (!fresh('household')) return; const text = $('list-text').value.trim(); if (!text) return; action(async () => { const result = await api('/v1/household',{text,kind,revision:data.household.revision}); $('list-text').value = ''; return result; }, 'List saved.'); };
function appendChatMessage(role, text, pending=false) {
  $('chat-welcome')?.remove();
  const message=document.createElement('article'); message.className='chat-message';message.dataset.role=role;
  message.innerHTML=`<div class="message-author">${role==='assistant' ? '<img src="/assets/icon.svg" alt="" width="20" height="20">' : ''}<span>${role==='assistant' ? 'Echo' : 'You'}</span></div><p class="message-text"></p>`;
  message.querySelector('.message-text').textContent=text;message.dataset.pending=String(pending);
  $('chat-reply').append(message);
  while($('chat-reply').children.length>60)$('chat-reply').firstElementChild.remove();
  $('chat-reply').scrollTop=$('chat-reply').scrollHeight;return message;
}
function finishChatMessage(message,result) {
  message.dataset.pending='false';message.querySelector('.message-text').textContent=result.text || 'Echo returned no text.';
  const links=document.createElement('div');links.className='source-links';
  for(const source of result.sources || []){try{const url=new URL(source.url);if(!['https:','http:'].includes(url.protocol))continue;const a=document.createElement('a');a.href=url.href;a.textContent=source.title || url.hostname;a.target='_blank';a.rel='noopener noreferrer';links.append(a);}catch{}}
  if(links.children.length)message.append(links);
  if(result.home_actions?.length){const details=document.createElement('details');details.className='action-receipts';details.innerHTML='<summary>Home action results</summary>'+result.home_actions.map(item=>`<p>${esc(human(item.action))} · ${esc(item.entity_id)} · ${esc(human(item.status))}</p>`).join('');message.append(details);}
  if(result.calendar_draft&&typeof attachCalendarDraft==='function')attachCalendarDraft(message,result.calendar_draft);
  $('chat-reply').scrollTop=$('chat-reply').scrollHeight;
}
function conversationChanged(){document.dispatchEvent(new Event('echo:conversation'));}
$('chat-form').onsubmit = async event => {
  event.preventDefault(); if (chatAbort || displayCaptureBusy || !fresh('timers') || signInRequired) return;
  const text=$('chat-text').value.trim();if(!text)return;
  const allow=$('allow-home').checked;$('allow-home').checked=false;
  chatAbort=new AbortController();$('stop-chat').hidden=false;guardButtons();conversationChanged();
  appendChatMessage('user',text);const answer=appendChatMessage('assistant','Thinking…',true);$('chat-text').value='';
  try {
    const result=await api('/v1/chat',{text,lookup:false,allow_home_actions:allow,calendar_review:true},'POST',chatAbort.signal);
    finishChatMessage(answer,result);
  } catch(error){finishChatMessage(answer,{text:error.name==='AbortError' ? 'Stopped waiting. Any action already sent may still complete.' : error.message});}
  finally{chatAbort=null;$('stop-chat').hidden=true;guardButtons();conversationChanged();refresh();}
};
$('stop-chat').onclick = async () => {
  const request=chatAbort;if(!request)return;
  $('stop-chat').disabled=true;
  try{const activity=await api('/v1/chat/activity');if(activity.active && activity.id)await api('/v1/chat/activity/'+activity.id+'/stop',{});}
  catch{toast('Could not confirm Echo stopped. Check activity in the workspace.');}
  finally{request.abort();$('stop-chat').disabled=false;}
};
function savePreferences() { preferences = {clock24:$('clock24').checked,idle:Number($('idle-time').value),dim:$('night-dim').checked}; try { localStorage.setItem('echo-display-preferences',JSON.stringify(preferences)); } catch { toast('Preferences will last for this session only.'); } tick(); }
$('clock24').checked = preferences.clock24; $('idle-time').value = preferences.idle; $('night-dim').checked = preferences.dim;
for (const id of ['clock24','idle-time','night-dim']) $(id).onchange = savePreferences;
function ambient(show) { $('ambient').hidden = !show; if (show) { previousFocus = document.activeElement; $('wake-screen').focus(); showPhoto(); } else { lastInput = Date.now(); previousFocus?.focus(); } }
$('ambient-button').onclick = () => ambient(true); $('wake-screen').onclick = () => ambient(false);
function clearPhotos() { $('ambient-photo').hidden = true; $('ambient-photo').removeAttribute('src'); photos.forEach(url => URL.revokeObjectURL(url)); photos = []; }
function showPhoto() { if (photos.length) { $('ambient-photo').src = photos[photoIndex++ % photos.length]; $('ambient-photo').hidden = false; } }
$('photo-files').onchange = event => { clearPhotos(); const files = [...event.target.files]; for (const file of files.slice(0,20)) if (['image/jpeg','image/png','image/webp'].includes(file.type) && file.size <= 12_000_000) photos.push(URL.createObjectURL(file)); event.target.value = ''; toast(`${photos.length} photos ready for this session. Up to 20 photos, 12 MB each.`); };
$('clear-photos').onclick = () => { clearPhotos(); toast('Ambient photos cleared.'); };
for (const type of ['pointerdown','keydown','touchstart']) document.addEventListener(type, () => lastInput = Date.now(), {passive:true});
document.addEventListener('keydown', event => { if (!$('ambient').hidden) { if (event.key === 'Escape') ambient(false); if (event.key === 'Tab') { event.preventDefault(); $('wake-screen').focus(); } } });
function renderClock(element, formatter, now) {
  const label = formatter.format(now);
  if (element.getAttribute('aria-label') === label) return;
  const parts = formatter.formatToParts(now), period = parts.find(part => part.type === 'dayPeriod');
  const digits = document.createElement('span');
  digits.className = 'clock-digits';
  digits.textContent = parts.filter(part => part.type !== 'dayPeriod').map(part => part.value).join('').trim();
  digits.setAttribute('aria-hidden', 'true');
  element.setAttribute('role', 'timer');
  element.setAttribute('aria-label', label);
  element.replaceChildren(digits);
  if (period) {
    const marker = document.createElement('span');
    marker.className = 'clock-period'; marker.textContent = period.value;
    marker.setAttribute('aria-hidden', 'true');
    if (parts.indexOf(period) < parts.findIndex(part => part.type === 'hour')) element.prepend(marker);
    else element.append(marker);
  }
}
function tick() {
  const now = new Date(), formatter = new Intl.DateTimeFormat([], {hour:'numeric',minute:'2-digit',hour12:!preferences.clock24}), date = now.toLocaleDateString([], {weekday:'long',month:'long',day:'numeric'});
  renderClock($('home-clock'), formatter, now); renderClock($('ambient-clock'), formatter, now); $('home-date').textContent = date; $('ambient-date').textContent = date;
  $('greeting').textContent = now.getHours() < 12 ? 'Good morning.' : now.getHours() < 18 ? 'Good afternoon.' : 'Good evening.';
  $('ambient').classList.toggle('dim', preferences.dim);
  if (preferences.idle && Date.now() - lastInput > preferences.idle * 1000 && !chatAbort && !displayCaptureBusy && !busy && !document.body.classList.contains('screen-sleeping') && !document.querySelector('dialog[open]') && $('ambient').hidden) ambient(true);
  renderTimers(); guardButtons();
  renderConnection();
  if (!fresh('voice') || !fresh('timers') || signInRequired) renderVoice();
}
async function start() {
  const initial = location.hash.slice(1), ticket = new URLSearchParams(initial).get('ticket');
  if (ticket) { history.replaceState(null,'',location.pathname); try { await api('/v1/ui/session',{ticket}); } catch (error) { toast(error.message); } }
  page(titles[initial] ? initial : 'home'); tick(); await refresh();
  setInterval(refresh, 6000); setInterval(refreshVoice,1000); setInterval(tick,1000); setInterval(() => { if (!$('ambient').hidden) showPhoto(); },30000);
}
document.addEventListener('DOMContentLoaded',start);

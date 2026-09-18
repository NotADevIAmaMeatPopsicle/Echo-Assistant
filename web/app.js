'use strict';
const $ = id => document.getElementById(id);
const settingsPage = location.pathname === '/settings';
const memoryPage = location.pathname === '/memory';
const devicesPage = location.pathname === '/devices';
const tasksPage = location.pathname === '/tasks';
const routinesPage = location.pathname === '/routines';
const activePanel = tasksPage ? 'tasks-panel' : routinesPage ? 'routines-panel' : devicesPage ? 'devices-panel' : memoryPage ? 'memory-panel' : settingsPage ? 'settings-panel' : 'chat-panel';
let state, dirty = false, authenticated = false, busy = false;
let chatActivity = null, activityPolling = false, chatStopping = false;
let speechEngines = [], voiceChecking = false;
let speakerCheckId = null, speakerCheckPolling = false;
const showError = text => { $('error').textContent = text; $('error').classList.toggle('hidden', !text); };
async function api(path, method = 'GET', body) {
  const response = await fetch(path, {method, credentials: 'same-origin', headers: {'Content-Type':'application/json','X-Echo-Request':'1'}, body: body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) { if (response.status === 401) { lock(); throw new Error(path === '/v1/ui/session' ? 'This sign-in link expired or was already used. Double-click Open Echo.cmd for a fresh link.' : 'Double-click Open Echo.cmd in the Echo-Assistant folder to sign in.'); } throw new Error(data.detail || 'The request failed.'); }
  return data;
}
function lock() { authenticated = false; $('locked').classList.remove('hidden'); for (const id of ['chat-panel','settings-panel','memory-panel','devices-panel','routines-panel','tasks-panel','logout']) $(id).classList.add('hidden'); }
function providerFields() {
  const p = $('provider').value;
  $('endpoint-field').classList.toggle('hidden', p !== 'local');
  $('azure-endpoint-field').classList.toggle('hidden', p !== 'azure');
  $('azure-deployment-note').classList.toggle('hidden', p !== 'azure');
  $('key-fields').classList.toggle('hidden', p === 'disabled');
  $('key-status').textContent = state?.credentials[p] ? 'Key saved' : p === 'local' ? 'Optional' : 'No key saved';
  $('provider-note').textContent = p === 'disabled' ? 'Built-in clock, timers and configured home controls remain available.' : p === 'local' ? 'Conversation goes to your selected local server. No automatic cloud fallback.' : 'When selected, your messages, personality instructions, and recent conversation are sent to this provider. Microphone audio stays local. API usage may be billed by the provider.';
  for (const id of ['load-models','test-provider']) $(id).disabled = p === 'disabled';
}
function fillSettings(data) {
  state = data; const s = data.settings;
  $('agent-runtime').value = s.agent_runtime || 'direct';
  $('web-lookup').value = s.web_lookup; $('memory-enabled').checked = s.memory_enabled;
  for (const [id,key] of Object.entries({'provider':'provider','model':'model','local-url':'local_url','azure-url':'azure_url','personality':'personality','response-budget':'max_output_tokens','stt-engine':'stt_engine','tts-engine':'tts_engine','tts-rate':'tts_rate'})) $(id).value = s[key];
  if (settingsPage) voiceFields(s.tts_voice);
  $('api-key').value = ''; $('clear-key').checked = false; dirty = false; providerFields(); rateLabel();
}
function rateLabel() { const v = Number($('tts-rate').value); $('rate-label').textContent = v === 0 ? 'Normal' : `${v > 0 ? '+' : ''}${v}`; }
function showChatActivity(activity) {
  chatActivity = activity;
  $('chat-activity').classList.toggle('hidden', activity.state === 'idle');
  $('chat-activity-caption').textContent = activity.caption || '';
  $('chat-stop').classList.toggle('hidden', !activity.active);
  $('chat-stop').disabled = chatStopping || activity.cancel_requested;
  $('chat-stop').textContent = activity.cancel_requested ? 'Stopping…' : 'Stop request';
  $('send').disabled = busy || activity.active;
  $('clear-chat').disabled = busy || activity.active;
  if (routinesPage) for (const button of document.querySelectorAll('.routine-run')) button.disabled = busy || activity.active || button.dataset.ready !== 'true';
  const list = $('chat-activity-events'); list.replaceChildren();
  for (const event of (activity.events || []).slice(-4)) {
    const row = document.createElement('li'); row.textContent = event.caption; list.append(row);
  }
  $('chat-activity-note').textContent = activity.active ? 'Stop cancels pending work. A home action already sent cannot be undone.' :
    activity.state === 'unconfirmed' ? 'New home actions are blocked for this request. The agent could not confirm stopping; check the receipts before retrying.' :
    activity.state === 'cancelled' ? 'Pending work stopped. Any actions already sent are listed below.' : '';
  const receipts = $('chat-activity-receipts'); receipts.replaceChildren();
  for (const action of activity.home_actions || []) {
    const row = document.createElement('p');
    const status = {complete:'Verified',accepted:'Accepted; result not verified',unconfirmed:'Not confirmed',denied:'Not allowed',unavailable:'Unavailable'};
    row.textContent = `${status[action.status] || 'Not confirmed'} · ${action.entity_id} · ${action.action.replaceAll('_',' ')}${action.value == null ? '' : ' '+action.value+(action.unit || '')}`;
    receipts.append(row);
  }
  if (activity.active) {
    $('orb-label').textContent = activity.state === 'acting' ? 'Taking care of it.' : activity.state === 'checking' ? 'Checking your home.' : activity.state === 'searching' ? 'Looking it up.' : activity.cancel_requested ? 'Stopping…' : 'Thinking it through.';
    $('orb-detail').textContent = activity.caption;
    document.querySelector('.device').classList.add('thinking');
  }
}
async function refreshChatActivity() {
  if (!authenticated || !['chat-panel','routines-panel'].includes(activePanel) || activityPolling) return;
  activityPolling = true;
  try { showChatActivity(await api('/v1/chat/activity')); }
  catch { if (chatActivity?.active) $('chat-activity-caption').textContent = 'Connection lost. Request status is unknown.'; }
  finally { activityPolling = false; }
}
$('chat-stop').addEventListener('click', async () => {
  const id = chatActivity?.id; if (!id || !chatActivity.active || chatStopping) return;
  chatStopping = true; $('chat-stop').disabled = true; showError('');
  try { showChatActivity(await api(`/v1/chat/activity/${encodeURIComponent(id)}/stop`, 'POST')); }
  catch(error) { showError(error.message); }
  finally { chatStopping = false; await refreshChatActivity(); }
});
function voiceFields(selectedVoice) {
  const engine = speechEngines.find(e => e.id === $('tts-engine').value);
  $('tts-voice').replaceChildren();
  if (!engine) return;
  for (const voice of engine.voices) { const option = document.createElement('option'); option.value = voice.id; option.textContent = voice.name; $('tts-voice').append(option); }
  const selected = selectedVoice === undefined ? engine.default_voice : selectedVoice || engine.default_voice;
  if (!engine.voices.some(v => v.id === selected)) {
    const option = document.createElement('option'); option.value = selected; option.textContent = `${selected} · unavailable`; option.disabled = true; $('tts-voice').append(option);
  }
  $('tts-voice').value = selected;
  $('tts-rate').disabled = !engine.pace;
  if (!engine.pace) $('tts-rate').value = 0;
  $('pace-note').textContent = engine.pace ? '' : 'Pocket uses its natural speaking pace.';
  $('voice-note').textContent = !engine.available ? 'This engine needs local setup before it can be used.' : engine.id === 'pocket' ? 'Conversational English · six preset voices · CPU only' : engine.id === 'kokoro' ? 'American and British English · 28 voices · CPU only' : 'Uses the voices installed with Windows.';
  $('check-voice').disabled = !engine.available || voiceChecking; rateLabel();
}
async function refreshStatus() {
  try {
    const health = await api('/health'); $('connection').textContent = health.deployment_mode === 'validation' ? 'Validation host · actions off' : 'Local host online';
    const connected = ['usb_connected','wifi_connected'].includes(health.device_transport);
    const waiting = ['usb_waiting','wifi_waiting'].includes(health.device_transport);
    $('device-connection').textContent = connected ? 'CONNECTED' : waiting ? 'WAITING FOR DEVICE' : 'DEVICE OFFLINE';
    $('volume').textContent = health.speaker_muted === true ? 'OUTPUT MUTED' : health.speaker_muted === false ? 'OUTPUT ON' : 'OUTPUT —';
    if (!busy) {
      const states = {armed:['Hello there.','Here when you need me'], activation:['I’m listening.','Go ahead'],
        listening:['I’m listening.','Take your time'], thinking:['Thinking…','Connecting the dots'],
        speaking:[health.speaker_muted ? 'Reply ready.' : 'Speaking…', health.speaker_muted ? 'Speaker output is muted' : 'A thought for you'],
        music:['Your music.','Playing on the device'], alarm:['Time’s up.','Check your timer'], muted:['Mic is muted.','Touch controls are available']};
      const state = connected ? (states[health.wake_word] || ['Hello there.','Here when you need me']) : waiting ? ['Waiting for Echo.','Check its power and connection. It will reconnect automatically.'] : ['Device offline.','Waiting for your device'];
      $('orb-label').textContent = state[0]; $('orb-detail').textContent = state[1];
      document.querySelector('.device').classList.toggle('thinking', health.wake_word === 'thinking');
    }
    if (authenticated) {
      const echo = await api('/v1/echo');
      if (echo.runtime === 'hermes' && ['starting','thinking','checking','acting'].includes(echo.activity?.state)) {
        $('orb-label').textContent = echo.activity.state === 'acting' ? 'Taking care of it.' : echo.activity.state === 'checking' ? 'Checking your home.' : 'Thinking it through.';
        $('orb-detail').textContent = echo.activity.caption;
        document.querySelector('.device').classList.add('thinking');
      }
      $('memory-mode').textContent = echo.memory === 'explicit_facts' ? 'Saved facts + session' : 'Session only';
      $('chat-lookup').disabled = echo.lookup !== 'available';
      if (echo.lookup !== 'available') $('chat-lookup').checked = false;
      $('chat-lookup').title = echo.lookup === 'available' ? 'Request an answer with web sources' : 'Enable web lookup in Settings with Azure or OpenAI';
      $('chat-home-actions').disabled = health.deployment_mode === 'validation' || $('chat-lookup').checked;
      if ($('chat-home-actions').disabled) $('chat-home-actions').checked = false;
      $('provider-label').textContent = echo.status === 'configured' ? `${echo.runtime === 'hermes' ? 'HERMES · ' : ''}${echo.provider.toUpperCase()} / ${echo.model}` : 'Choose a provider in Settings';
      $('privacy-note').textContent = echo.cloud ? 'Local speech. Cloud conversation selected.' : 'Local speech. Your choice of conversation.';
      const empty = $('messages').querySelector('.empty-chat p');
      if (empty && echo.status === 'configured') empty.textContent = 'Ask a question, untangle an idea, or follow a curiosity. Recent messages stay in memory for this session.';
      if (settingsPage && !speakerCheckPolling) {
        try { showSpeakerCheck(await api('/v1/settings/speaker-check')); } catch { /* Other controls remain available. */ }
      }
      if (settingsPage) showAgentSettings(await api('/v1/settings/agent'));
    }
  } catch { $('connection').textContent = 'Host unavailable'; $('device-connection').textContent = 'HOST OFFLINE'; }
}
function showSpeakerCheck(result) {
  const active = ['queued','generating','playing'].includes(result.status);
  speakerCheckId = active ? result.id : null;
  $('hear-echo').disabled = active;
  $('stop-speaker-check').classList.toggle('hidden', !active);
  const messages = {idle:'', queued:'Waiting for Echo…', generating:'Preparing the saved voice locally…', playing:'Playing on Echo. Volume is unchanged.',
    complete:'Sample finished on Echo. No audio was saved.', cancelled:'Sample stopped.', failed:result.reason || 'The speaker could not complete the sample.'};
  $('speaker-check-result').textContent = active && result.cancel_requested ? 'Stopping the sample…' : messages[result.status] || '';
}
function showAgentSettings(result) {
  $('agent-apply-controls').classList.toggle('hidden', result.status === 'not_required');
  const messages = {active:'Active. Hermes has your saved model configuration. Test connection checks that the provider responds.',
    pending:'Saved changes need to be applied to Echo before its next conversation.',
    queued:'Queued on Remote host. Usually starts within one minute. You can cancel before it starts.',
    applying:'Applying the saved model settings. Your display, microphone and music stay connected.',
    failed:result.reason || 'The change was not applied. Review your settings and try again.'};
  $('agent-apply-status').textContent = messages[result.status] || '';
  $('apply-agent').disabled = !result.managed || !['pending','failed'].includes(result.status);
  $('cancel-agent-apply').classList.toggle('hidden', result.status !== 'queued');
}
for (const [id, method] of [['apply-agent','POST'],['cancel-agent-apply','DELETE']]) $(id).addEventListener('click', async () => {
  if (dirty) { showError('Save your settings before applying them.'); return; }
  $(id).disabled = true; showError('');
  try { showAgentSettings(await api('/v1/settings/apply-agent', method)); }
  catch(error) { showError(error.message); }
  finally { $(id).disabled = false; await refreshStatus(); }
});
function addMessage(role, text, unavailable = false, sources = [], lookedUp = false, homeActions = []) {
  $('messages').querySelector('.empty-chat')?.remove();
  const item = document.createElement('div'); item.className = `message ${role}${unavailable ? ' unavailable' : ''}`;
  const name = document.createElement('small'); name.textContent = role === 'user' ? 'YOU' : 'ECHO';
  item.append(name);
  const safeSources = Array.isArray(sources) ? sources : [];
  const sourceLink = (source, label) => {
    try {
      const url = new URL(source.url);
      if (url.protocol !== 'https:' || url.username || url.password) return document.createTextNode(label);
      const link = document.createElement('a'); link.href = url.href; link.textContent = label;
      link.target = '_blank'; link.rel = 'noopener noreferrer'; link.className = 'citation'; link.title = source.title || url.hostname; return link;
    } catch { return document.createTextNode(label); }
  };
  for (const part of text.split(/(\[\d+\]|\*\*[^*]+\*\*)/g)) {
    const match = /^\[(\d+)\]$/.exec(part), source = match && safeSources[Number(match[1])-1];
    if (part.startsWith('**') && part.endsWith('**')) { const strong = document.createElement('strong'); strong.textContent = part.slice(2,-2); item.append(strong); }
    else item.append(source ? sourceLink(source,part) : document.createTextNode(part));
  }
  if (safeSources.length) {
    const list = document.createElement('div'); list.className = 'sources';
    const label = document.createElement('small'); label.textContent = lookedUp ? 'WEB SOURCES' : 'SOURCES'; list.append(label);
    safeSources.forEach((source,i) => list.append(sourceLink(source,`[${i+1}] ${source.title || source.url}`)));
    item.append(list);
  }
  if (Array.isArray(homeActions) && homeActions.length) {
    const list = document.createElement('div'); list.className = 'sources';
    const title = document.createElement('small'); title.textContent = 'HOME ACTIONS'; list.append(title);
    const labels = {complete:'Verified', accepted:'Accepted · result not verified', unconfirmed:'Not confirmed', denied:'Not allowed', unavailable:'Unavailable'};
    for (const action of homeActions) {
      const receipt = document.createElement('p');
      const setting = action.value == null ? '' : ` ${action.value}${action.unit || ''}`;
      receipt.textContent = `${labels[action.status] || 'Not confirmed'} · ${action.entity_id} · ${action.action.replaceAll('_',' ')}${setting}${action.error ? ' · '+action.error : ''}`;
      list.append(receipt);
    }
    item.append(list);
  }
  $('messages').append(item); $('messages').scrollTop = $('messages').scrollHeight;
  while ($('messages').children.length > 40) $('messages').firstElementChild.remove();
}
$('chat-form').addEventListener('submit', async event => {
  event.preventDefault(); const message = $('message').value.trim(); if (!message || busy) return;
  busy = true; $('send').disabled = true; $('clear-chat').disabled = true; $('message').value = ''; showError(''); addMessage('user', message);
  document.querySelector('.device').classList.add('thinking'); $('orb-label').textContent = 'Thinking…'; $('orb-detail').textContent = 'A moment to connect the dots';
  const allowActions = $('chat-home-actions').checked;
  $('chat-home-actions').checked = false;
  try { const result = await api('/v1/chat','POST',{text:message,lookup:$('chat-lookup').checked,allow_home_actions:allowActions}); addMessage('assistant', result.display_text || result.text, result.status !== 'complete', result.sources, result.looked_up, result.home_actions); }
  catch (error) { showError(error.message); }
  finally { busy = false; $('send').disabled = false; $('clear-chat').disabled = false; document.querySelector('.device').classList.remove('thinking'); await refreshChatActivity(); await refreshStatus(); $('message').focus(); }
});
$('message').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {event.preventDefault(); $('chat-form').requestSubmit();} });
$('chat-lookup').addEventListener('change', refreshStatus);
$('clear-chat').addEventListener('click', async () => { try {await api('/v1/chat','DELETE'); $('messages').replaceChildren(); showError(''); await refreshChatActivity();} catch(error) {showError(error.message);} });
$('settings-panel').addEventListener('input', () => { dirty = true; $('save-status').textContent = 'You have unsaved changes.'; });
$('provider').addEventListener('change', () => { $('api-key').value = ''; $('clear-key').checked = false; $('model').value = ''; $('model-options').replaceChildren(); $('provider-result').textContent = ''; providerFields(); });
$('tts-rate').addEventListener('input', rateLabel);
$('tts-engine').addEventListener('change', () => {voiceFields(); $('voice-result').textContent = '';});
for (const id of ['tts-voice','tts-rate']) $(id).addEventListener('input', () => { $('voice-result').textContent = ''; });
$('check-voice').addEventListener('click', async () => {
  voiceChecking = true; $('check-voice').disabled = true; showError('');
  const selection = {tts_engine:$('tts-engine').value,tts_voice:$('tts-voice').value,tts_rate:Number($('tts-rate').value)};
  const name = $('tts-voice').selectedOptions[0]?.textContent || 'Default voice';
  $('voice-result').textContent = 'Checking locally… First use also loads the model. The speaker stays silent.';
  try {
    const result = await api('/v1/settings/check-voice','POST',selection);
    const seconds = (result.generation_ms / 1000).toFixed(2);
    $('voice-result').textContent = `${name}: passed. Generated ${result.seconds.toFixed(1)} seconds of speech in ${seconds}s. Nothing was played. Save to use your selection.`;
  } catch(error) { $('voice-result').textContent = error.message; }
  finally {voiceChecking = false; $('check-voice').disabled = false;}
});
$('hear-echo').addEventListener('click', async () => {
  if (dirty) { $('speaker-check-result').textContent = 'Save your voice settings first, then try the speaker sample.'; return; }
  $('hear-echo').disabled = true;
  speakerCheckPolling = true;
  $('speaker-check-result').textContent = 'Requesting a quiet sample on Echo…';
  try {
    const started = await api('/v1/settings/speaker-check','POST');
    speakerCheckId = started.id;
    const requestedId = started.id;
    $('stop-speaker-check').classList.remove('hidden');
    for (let attempt = 0; attempt < 150; attempt++) {
      await new Promise(resolve => setTimeout(resolve,400));
      const result = await api('/v1/settings/speaker-check');
      if (result.id !== requestedId) throw new Error('The speaker check changed. Check Echo before trying again.');
      showSpeakerCheck(result);
      if (['complete','cancelled','failed'].includes(result.status)) break;
      if (attempt === 149) throw new Error('The speaker has not confirmed completion. The sample request expires automatically.');
    }
  } catch (error) { $('speaker-check-result').textContent = error.message; }
  finally { speakerCheckPolling = false; speakerCheckId = null; $('hear-echo').disabled = false; $('stop-speaker-check').classList.add('hidden'); }
});
$('stop-speaker-check').addEventListener('click', async () => {
  if (!speakerCheckId) return;
  try {
    await api('/v1/settings/speaker-check/'+encodeURIComponent(speakerCheckId),'DELETE');
    $('speaker-check-result').textContent = 'Stopping the sample…';
  } catch (error) { $('speaker-check-result').textContent = error.message; }
});
$('apply-speech').addEventListener('click', async () => {
  if (dirty) {showError('Save your settings before applying the recognition choice.'); return;}
  $('apply-speech').disabled = true; showError('');
  try {
    await api('/v1/settings/apply-speech','POST'); $('speech-note').textContent = 'Restarting the bridge with your saved recognition choice. Speaker volume is unchanged.';
    for (let attempt = 0; attempt < 35; attempt++) {
      await new Promise(resolve => setTimeout(resolve,2000));
      const speech = await api('/v1/settings/speech');
      if (speech.apply_status === 'ready') {$('speech-note').textContent = `Active recognition: ${speech.active_stt}. Voice and pace apply to the next reply. Output volume is unchanged.`; break;}
      if (speech.apply_status === 'failed') throw new Error('The bridge could not restart. Check the device connection, then try again.');
      if (attempt === 34) throw new Error('The bridge has not confirmed the new recognition engine yet.');
    }
    await refreshStatus();
  } catch(error) {showError(error.message);} finally {$('apply-speech').disabled = false;}
});
$('settings-panel').addEventListener('submit', async event => {
  event.preventDefault(); showError(''); $('save').disabled = true;
  const settings = {agent_runtime:$('agent-runtime').value,provider:$('provider').value, model:$('model').value.trim(), local_url:$('local-url').value.trim(), azure_url:$('azure-url').value.trim(), personality:$('personality').value.trim(), max_output_tokens:Number($('response-budget').value), stt_engine:$('stt-engine').value, tts_engine:$('tts-engine').value, tts_voice:$('tts-voice').value, tts_rate:Number($('tts-rate').value),web_lookup:$('web-lookup').value,memory_enabled:$('memory-enabled').checked};
  const body = {settings, clear_key:$('clear-key').checked}; if ($('api-key').value.trim()) body.api_key = $('api-key').value.trim();
  try { const previous = state.settings.stt_engine; fillSettings(await api('/v1/settings','PUT',body)); $('save-status').textContent = previous !== settings.stt_engine ? 'Saved. Use Apply recognition choice to restart the bridge. Output volume is unchanged.' : settings.agent_runtime === 'hermes' ? 'Saved. Check the model settings status above; apply model or key changes when needed.' : 'Saved. Echo will use these settings on the next reply.'; await refreshStatus(); }
  catch(error) {showError(error.message);} finally { $('api-key').value = ''; $('save').disabled = false; }
});
for (const [id,path] of [['load-models','models'],['test-provider','test']]) $(id).addEventListener('click', async () => {
  if (dirty) { $('provider-result').textContent = 'Save your settings first, then try again.'; return; }
  $(id).disabled = true; $('provider-result').textContent = 'Connecting…'; showError('');
  try { const result = await api(`/v1/settings/${path}`,'POST');
    if (result.models) { $('model-options').replaceChildren(); for (const model of result.models) {const option = document.createElement('option'); option.value = model; $('model-options').append(option);} $('provider-result').textContent = `${result.models.length} models available. Select or type a model ID above, then save.`; $('model').focus(); }
    else $('provider-result').textContent = result.text;
  } catch(error) { $('provider-result').textContent = error.message; } finally { $(id).disabled = false; }
});
$('logout').addEventListener('click', async () => { try {await api('/v1/ui/session','DELETE'); $('messages').replaceChildren(); lock();} catch(error) {showError(error.message);} });
window.addEventListener('beforeunload', event => { if (dirty) {event.preventDefault(); event.returnValue = '';} });
let memories = [], editingMemory = null;
function resetMemoryEditor() {
  editingMemory = null; $('memory-text').value = ''; $('memory-save').textContent = 'Save memory';
  $('memory-cancel').classList.add('hidden');
}
function renderMemories() {
  const filter = $('memory-filter').value.toLocaleLowerCase(); $('memory-list').replaceChildren();
  const shown = memories.filter(item => item.text.toLocaleLowerCase().includes(filter));
  if (!shown.length) { const empty = document.createElement('p'); empty.className = 'hint'; empty.textContent = memories.length ? 'No matching memories.' : 'Nothing saved yet. Add a fact above, or say “Remember that…” to Echo.'; $('memory-list').append(empty); }
  for (const item of shown) {
    const row = document.createElement('article'); row.className = 'memory-item';
    const content = document.createElement('p'); content.textContent = item.text;
    const date = document.createElement('small'); date.textContent = 'Updated '+new Date(item.updated_at*1000).toLocaleDateString();
    const actions = document.createElement('div'); actions.className = 'actions';
    const edit = document.createElement('button'); edit.type = 'button'; edit.className = 'secondary'; edit.textContent = 'Edit';
    edit.addEventListener('click', () => { editingMemory = item.id; $('memory-text').value = item.text; $('memory-save').textContent = 'Save changes'; $('memory-cancel').classList.remove('hidden'); $('memory-text').focus(); });
    const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'quiet'; remove.textContent = 'Delete'; remove.setAttribute('aria-label','Delete memory: '+item.text.slice(0,70));
    remove.addEventListener('click', async () => { remove.disabled = true; try { await api('/v1/memory/'+item.id,'DELETE'); if (editingMemory === item.id) resetMemoryEditor(); await loadMemories(); } catch(error) {showError(error.message);remove.disabled = false;} });
    actions.append(edit,remove); row.append(content,date,actions); $('memory-list').append(row);
  }
  $('memory-count').textContent = `${memories.length} / 200`;
  $('memory-clear').disabled = $('memory-export').disabled = memories.length === 0;
}
async function loadMemories() {
  const result = await api('/v1/memory'); memories = result.items;
  $('memory-state').textContent = result.enabled ? 'Memory is on. Only facts you explicitly save are kept.' : 'Memory is paused. Echo will not save or use facts in conversation; you can manage them here.';
  renderMemories();
}
$('memory-filter').addEventListener('input',renderMemories);
$('memory-cancel').addEventListener('click',resetMemoryEditor);
$('memory-form').addEventListener('submit',async event => {
  event.preventDefault(); const text = $('memory-text').value.trim(); if (!text) return;
  $('memory-save').disabled = true; showError('');
  try { await api('/v1/memory'+(editingMemory ? '/'+editingMemory : ''),editingMemory ? 'PUT' : 'POST',{text}); resetMemoryEditor(); await loadMemories(); }
  catch(error) {showError(error.message);} finally {$('memory-save').disabled = false;}
});
$('memory-clear').addEventListener('click',async () => {
  if (!window.confirm(`Delete all ${memories.length} saved memories? This cannot be undone.`)) return;
  try { await api('/v1/memory','DELETE'); resetMemoryEditor(); await loadMemories(); } catch(error) {showError(error.message);}
});
$('memory-export').addEventListener('click',() => {
  const url = URL.createObjectURL(new Blob([JSON.stringify({version:1,memories},null,2)],{type:'application/json'}));
  const link = document.createElement('a'); link.href = url; link.download = 'echo-memories.json'; link.click();
  setTimeout(() => URL.revokeObjectURL(url),1000);
});
let homeInventory, homeDraft;
let roomRequest=false, roomLoad=0;
async function loadRoomCards() {
  const generation=++roomLoad;
  const data=(await api('/v1/home')).lights;
  if(generation!==roomLoad)return;
  $('room-cards').replaceChildren();
  if(data?.status!=='available') {$('room-result').textContent='Home Assistant light status is unavailable.';return;}
  for(const room of data.rooms) {
    const card=document.createElement('button');card.className='room-card '+room.state;card.type='button';
    const title=document.createElement('strong');title.textContent=room.name;
    const detail=document.createElement('span');detail.textContent=room.state==='unassigned'?'Assign lights below':room.state==='unavailable'?'Unavailable':`${room.state==='mixed'?'Some on':room.state==='on'?'On':'Off'} · ${room.count} light${room.count===1?'':'s'}`;
    card.append(title,detail);card.disabled=!room.available || roomRequest || dirty;
    card.setAttribute('aria-label',`${room.name}: ${detail.textContent}${room.available?'. Turn '+(room.on?'off':'on'):''}`);
    card.addEventListener('click',async()=>{
      if(roomRequest || dirty)return;
      roomRequest=true;++roomLoad;for(const c of $('room-cards').children)c.disabled=true;
      $('room-result').textContent=`Updating ${room.name}…`;
      try {
        const result=await api(`/v1/home/rooms/${room.id}/actions`,'POST',{action:room.on?'turn_off':'turn_on',revision:data.revision});
        $('room-result').textContent=result.verified?`${room.name} ${room.on?'off':'on'}.`:'Request accepted. Waiting for Home Assistant state.';
      } catch(error) {$('room-result').textContent=error.message;}
      finally {roomRequest=false;await loadRoomCards().catch(()=>{$('room-result').textContent='Could not refresh light status.';});}
    });
    $('room-cards').append(card);
  }
}
$('room-refresh').addEventListener('click',()=>loadRoomCards().catch(error=>showError(error.message)));
function homeEditing(enabled) {
  for(const control of $('devices-panel').querySelectorAll('input,select,button')) {
    if(enabled && control.classList.contains('room-card'))continue;
    control.disabled=!enabled;
  }
  $('home-refresh').disabled=lightActionBusy;
  syncLightButtons(!enabled);
}
let lightActionBusy=false;
const lightResults=new Map();
function syncLightButtons(disabled=false) {
  for(const button of $('device-list').querySelectorAll('[data-light-action]')) {
    const device=homeInventory?.devices.find(d=>d.entity_id===button.dataset.entity);
    const rule=device && (homeDraft.devices[device.entity_id] || {access:homeDraft.default_access});
    button.disabled=disabled || lightActionBusy || dirty || !device?.available || !['on','off'].includes(device?.state) || rule?.access==='hidden' || device.state===button.dataset.lightAction;
  }
}
async function controlLight(device, target) {
  if(lightActionBusy || dirty)return;
  lightActionBusy=true;homeEditing(false);$('home-refresh').disabled=true;showError('');
  lightResults.set(device.entity_id,'Requesting '+target+'…');renderDevices();
  try {
    const result=await api(`/v1/home/lights/${encodeURIComponent(device.entity_id)}/actions`,'POST',{action:'turn_'+target,revision:homeInventory.revision});
    device.state=result.state || 'unknown';device.available=['on','off'].includes(device.state);
    lightResults.set(device.entity_id,result.verified?`${result.status==='already_set'?'Already':'Confirmed'} ${target}. It stays ${target} until changed.`:'Request accepted; the new state is not confirmed. Refresh to check.');
    await loadRoomCards();
  } catch(error) {
    device.state='unknown';device.available=false;lightResults.set(device.entity_id,error.message);showError(error.message);
  } finally {lightActionBusy=false;renderDevices();homeEditing(true);}
}
function renderDevices() {
  const query = $('device-filter').value.toLocaleLowerCase();
  const domain = $('device-domain').value;
  const room = $('device-room-filter').value;
  $('device-list').replaceChildren();
  const matches = homeInventory.devices.filter(d => {
    const area = homeDraft.devices[d.entity_id]?.room || d.ha_area || '';
    return (!domain || d.domain === domain) && (!room || (room === '__none' ? !area : area === room)) &&
      [d.name,d.entity_id,area].join(' ').toLocaleLowerCase().includes(query);
  });
  $('device-count').textContent = `${matches.length} / ${homeInventory.devices.length}`;
  for (const device of matches) {
    const rule = homeDraft.devices[device.entity_id] || {access:homeDraft.default_access,room:''};
    const row = document.createElement('article'); row.className = 'home-device';
    const heading = document.createElement('div'); heading.className = 'section-heading';
    const name = document.createElement('h3'); name.textContent = device.name;
    const badge = document.createElement('span'); badge.className = 'pill'+(device.available ? '' : ' unavailable');
    badge.textContent = device.available ? 'AVAILABLE' : 'UNAVAILABLE'; heading.append(name,badge);
    const identity = document.createElement('small'); identity.className = 'device-identity'; identity.textContent = device.entity_id;
    const reading = document.createElement('p'); reading.className = 'device-state';
    reading.textContent = `${device.state ?? 'Unknown'} · ${device.ha_area ? 'HA room: '+device.ha_area : 'No Home Assistant room'}`;
    const fields = document.createElement('div'); fields.className = 'two-col';
    const permission = document.createElement('label'); permission.textContent = 'Echo agent access';
    const select = document.createElement('select');
    const choices = [['read','Read state'],['hidden','Hidden']];
    if (device.control_supported) choices.splice(1,0,['control','Control']);
    for (const [value,label] of choices) {const option = document.createElement('option'); option.value=value;option.textContent=label;select.append(option);}
    select.value = rule.access; select.setAttribute('aria-label','Echo access for '+device.name);
    const roomLabel = document.createElement('label'); roomLabel.textContent = 'Room for Echo';
    const input = document.createElement('input'); input.maxLength=60;input.value=rule.room;input.setAttribute('list','home-room-names');
    input.placeholder = device.ha_area || 'Choose or name a room';input.setAttribute('aria-label','Echo room for '+device.name);
    const edit = () => {homeDraft.devices[device.entity_id]={access:select.value,room:input.value.trim()};dirty=true;for(const card of $('room-cards').children)card.disabled=true;syncLightButtons();$('home-save-status').textContent='You have unsaved device settings. Save before using light controls.';};
    select.addEventListener('change',edit);input.addEventListener('input',edit);
    permission.append(select);roomLabel.append(input);fields.append(permission,roomLabel);
    row.append(heading,identity,reading,fields);
    if(device.domain==='light') {
      const controls=document.createElement('div');controls.className='actions light-controls';
      for(const target of ['on','off']) {
        const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent='Turn '+target;
        button.dataset.entity=device.entity_id;button.dataset.lightAction=target;button.setAttribute('aria-label',`Turn ${device.name} ${target}`);
        button.addEventListener('click',()=>controlLight(device,target));controls.append(button);
      }
      const feedback=document.createElement('p');feedback.className='inline-result';feedback.setAttribute('role','status');
      feedback.textContent=lightResults.get(device.entity_id) || (rule.access==='hidden'?'Unhide and save this light to use its controls.':'Controls only this bulb. Its state stays as chosen.');
      row.append(controls,feedback);
    }
    $('device-list').append(row);
  }
  if (!matches.length) { const empty=document.createElement('p');empty.className='notice';empty.textContent='No devices match these filters.';$('device-list').append(empty); }
  syncLightButtons();
  if(lightActionBusy)homeEditing(false);
}
async function loadDevices() {
  homeInventory = await api('/v1/home/devices');homeDraft=structuredClone(homeInventory.policy);
  lightResults.clear();
  $('home-default-access').value=homeDraft.default_access;
  $('home-summary').textContent=`${homeInventory.counts.available} available · ${homeInventory.counts.unavailable} unavailable · ${homeInventory.counts.without_area} without a room`;
  $('home-registry').textContent=homeInventory.registry_available ? 'Rooms come from Home Assistant. An Echo room below overrides them only for this assistant.' : 'Home Assistant room information is unavailable. Echo assignments still work; other rooms remain unknown.';
  $('home-save-status').textContent=homeInventory.applied ? 'Settings applied to Echo on Remote host.' : 'Saved choices will be checked with Remote host before its next conversation.';
  $('home-retry').classList.toggle('hidden',homeInventory.applied);
  const rooms=[...new Set(['Bedroom','Living Room','Dining Room','Patio',...homeInventory.ha_areas,...homeInventory.areas])].sort();
  $('home-room-names').replaceChildren();for(const room of rooms){const option=document.createElement('option');option.value=room;$('home-room-names').append(option);}
  const previous=$('device-room-filter').value;$('device-room-filter').replaceChildren();
  for(const [value,label] of [['','All rooms'],['__none','Unassigned'],...rooms.map(r=>[r,r])]){const option=document.createElement('option');option.value=value;option.textContent=label;$('device-room-filter').append(option);}
  $('device-room-filter').value=rooms.includes(previous)||previous==='__none'?previous:'';
  dirty=false;renderDevices();homeEditing(true);await loadRoomCards();
}
for(const id of ['device-filter','device-domain','device-room-filter']) $(id).addEventListener('input',()=>{if(homeInventory)renderDevices();});
$('home-default-access').addEventListener('change',()=>{homeDraft.default_access=$('home-default-access').value;dirty=true;for(const card of $('room-cards').children)card.disabled=true;$('home-save-status').textContent='You have unsaved device settings.';renderDevices();});
$('home-refresh').addEventListener('click',async()=>{
  if(dirty){showError('Save your device settings before refreshing.');return;}
  $('home-refresh').disabled=true;showError('');try{await loadDevices();}catch(error){showError(error.message);}finally{$('home-refresh').disabled=false;}
});
$('home-save').addEventListener('click',async()=>{
  homeEditing(false);$('home-refresh').disabled=true;showError('');$('home-save-status').textContent='Saving and applying to Echo…';
  try{await api('/v1/home/access','PUT',{revision:homeInventory.revision,policy:homeDraft});await loadDevices();}
  catch(error){showError(error.message);$('home-save-status').textContent='Application not confirmed. Refresh to review the saved state.';dirty=false;try{await loadDevices();}catch{}}
  finally{homeEditing(Boolean(homeInventory));}
});
$('home-retry').addEventListener('click',async()=>{
  $('home-retry').disabled=true;showError('');try{await api('/v1/home/access/retry','POST');await loadDevices();}catch(error){showError(error.message);}finally{$('home-retry').disabled=false;}
});
let routineItems = [], routineDevices = [], routineDraft = [], routineEditing = null;
const routineLabels = {turn_on:'Turn on',turn_off:'Turn off',brightness:'Brightness',color_temperature:'Color temperature',temperature:'Target temperature',mode:'Thermostat mode',volume:'Volume',mute:'Mute',play:'Play',pause:'Pause',stop:'Stop',activate:'Activate scene'};
function routineSpecs(device) {
  if (!device) return {};
  const a = device.attributes || {}, specs = {};
  const add = (key, spec = {}) => { specs[key] = spec; };
  if (['light','switch'].includes(device.domain)) {add('turn_on');add('turn_off');}
  if (device.domain === 'light') {
    const modes = Array.isArray(a.supported_color_modes) ? a.supported_color_modes : [];
    if (modes.some(m => ['brightness','color_temp','hs','xy','rgb','rgbw','rgbww','white'].includes(m))) add('brightness',{type:'number',min:0,max:100,step:1,suffix:'%'});
    if (modes.includes('color_temp') && Number.isFinite(a.min_color_temp_kelvin) && Number.isFinite(a.max_color_temp_kelvin)) add('color_temperature',{type:'number',min:a.min_color_temp_kelvin,max:a.max_color_temp_kelvin,step:1,suffix:'K'});
  }
  if (device.domain === 'climate') {
    if (a.temperature != null && ['°F','°C'].includes(a.temperature_unit) && Number.isFinite(a.min_temp) && Number.isFinite(a.max_temp)) add('temperature',{type:'number',min:a.min_temp,max:a.max_temp,step:a.target_temp_step || .5,suffix:a.temperature_unit,unit:a.temperature_unit});
    if (Array.isArray(a.hvac_modes) && a.hvac_modes.length) add('mode',{type:'select',values:a.hvac_modes});
  }
  if (device.domain === 'media_player') for (const [action,mask] of Object.entries({pause:1,volume:4,mute:8,turn_on:128,turn_off:256,play:16384,stop:4096})) {
    if ((a.supported_features || 0) & mask) add(action,action==='volume'?{type:'number',min:0,max:100,step:1,suffix:'%'}:action==='mute'?{type:'select',values:[true,false]}:{});
  }
  if (device.domain === 'scene') add('activate');
  return specs;
}
function routineDescription(step) {
  const device = routineDevices.find(d => d.entity_id === step.entity_id);
  const suffix = step.unit || (['volume','brightness'].includes(step.action) ? '%' : step.action==='color_temperature' ? ' K' : '');
  return `${device?.name || step.entity_id}: ${routineLabels[step.action] || step.action}${step.value == null ? '' : ' '+step.value+suffix}`;
}
function routineChanged() { dirty = true; }
function renderRoutineSteps() {
  const list = $('routine-steps'); list.replaceChildren();
  routineDraft.forEach((step,index) => {
    const row=document.createElement('fieldset'); row.className='routine-step';
    const legend=document.createElement('legend');legend.textContent=`Action ${index+1}`;row.append(legend);
    const deviceLabel=document.createElement('label');deviceLabel.textContent='Device';
    const select=document.createElement('select');select.required=true;
    const blank=document.createElement('option');blank.value='';blank.textContent='Choose a device';select.append(blank);
    for (const device of routineDevices.filter(d=>d.access!=='hidden' && Object.keys(routineSpecs(d)).length)) {
      const option=document.createElement('option');option.value=device.entity_id;option.textContent=device.name+(device.available?'':' · unavailable');select.append(option);
    }
    if (step.entity_id && !Array.from(select.options).some(o=>o.value===step.entity_id)) {
      const missing=document.createElement('option');missing.value=step.entity_id;missing.textContent=step.entity_id+' · unavailable';select.append(missing);
    }
    select.value=step.entity_id;deviceLabel.append(select);row.append(deviceLabel);
    select.addEventListener('change',()=>{routineDraft[index]={entity_id:select.value,action:'',value:null,unit:null};routineChanged();renderRoutineSteps();});
    const device=routineDevices.find(d=>d.entity_id===step.entity_id), specs=routineSpecs(device);
    const actionLabel=document.createElement('label');actionLabel.textContent='Action';const action=document.createElement('select');action.required=true;
    const choose=document.createElement('option');choose.value='';choose.textContent='Choose an action';action.append(choose);
    for (const key of Object.keys(specs)) {const option=document.createElement('option');option.value=key;option.textContent=routineLabels[key];action.append(option);}
    action.value=step.action;actionLabel.append(action);row.append(actionLabel);
    action.addEventListener('change',()=>{step.action=action.value;step.value=null;step.unit=specs[action.value]?.unit || null;routineChanged();renderRoutineSteps();});
    const spec=specs[step.action];
    if (spec?.type) {
      const label=document.createElement('label');label.textContent=spec.type==='number'?`Value (${spec.min}–${spec.max}${spec.suffix || ''})`:'Value';
      const input=document.createElement(spec.type==='select'?'select':'input');input.required=true;
      if (spec.type==='select') {
        const placeholder=document.createElement('option');placeholder.value='';placeholder.textContent='Choose a value';input.append(placeholder);
        for (const value of spec.values) {const option=document.createElement('option');option.value=String(value);option.textContent=typeof value==='boolean'?(value?'Muted':'Unmuted'):value;input.append(option);}
      } else {input.type='number';input.min=spec.min;input.max=spec.max;input.step=spec.step;}
      input.value=step.value == null?'':String(step.value);input.addEventListener('input',()=>{step.value=input.value===''?null:spec.type==='number'?Number(input.value):step.action==='mute'?input.value==='true':input.value;step.unit=spec.unit || null;routineChanged();});label.append(input);row.append(label);
    }
    if (device) {const hint=document.createElement('p');hint.className='hint';hint.textContent=!device.available?'Device unavailable. Restore its connection before saving or running.':device.access==='control'?'Control permission enabled.':'Read access. Enable Control on Devices before running this routine.';row.append(hint);}
    const controls=document.createElement('div');controls.className='actions';
    for (const [label,delta] of [['Move up',-1],['Move down',1],['Remove',0]]) {
      const button=document.createElement('button');button.type='button';button.className='quiet';button.textContent=label;button.disabled=delta<0?index===0:delta>0?index===routineDraft.length-1:false;
      button.addEventListener('click',()=>{if(delta)[routineDraft[index],routineDraft[index+delta]]=[routineDraft[index+delta],routineDraft[index]];else routineDraft.splice(index,1);routineChanged();renderRoutineSteps();});controls.append(button);
    }
    row.append(controls);list.append(row);
  });
  $('routine-add').disabled=routineDraft.length>=12;$('routine-save').disabled=!routineDraft.length;
}
function editRoutine(item=null) {
  routineEditing=item;routineDraft=structuredClone(item?.steps || []);$('routine-name').value=item?.name || '';
  $('routine-heading').textContent=item?'Edit routine':'New routine';$('routine-form').classList.remove('hidden');dirty=false;
  if(!routineDraft.length)routineDraft.push({entity_id:'',action:'',value:null,unit:null});renderRoutineSteps();$('routine-name').focus();
}
function renderRoutines() {
  const list=$('routine-list');list.replaceChildren();
  if(!routineItems.length){const empty=document.createElement('p');empty.className='notice';empty.textContent='No routines yet. Start with a few settings you often use together.';list.append(empty);}
  for(const item of routineItems) {
    const card=document.createElement('article');card.className='routine-card';const heading=document.createElement('h3');heading.textContent=item.name;card.append(heading);
    const steps=document.createElement('ol');for(const step of item.steps){const row=document.createElement('li');row.textContent=routineDescription(step);steps.append(row);}card.append(steps);
    const ready=item.steps.every(s=>{const d=routineDevices.find(d=>d.entity_id===s.entity_id);return d?.available && d.access==='control' && routineSpecs(d)[s.action];});
    const controls=document.createElement('div');controls.className='actions';
    const run=document.createElement('button');run.type='button';run.className='routine-run';run.textContent='Run';run.dataset.ready=String(ready);run.disabled=!ready || busy || chatActivity?.active;
    run.addEventListener('click',async()=>{
      if(busy || chatActivity?.active)return;busy=true;renderRoutines();$('routine-result').textContent=`Starting ${item.name}…`;showError('');
      try{const result=await api(`/v1/routines/${item.id}/run`,'POST',{revision:item.revision});$('routine-result').textContent=result.text;}
      catch(error){showError(error.message);$('routine-result').textContent='Result not confirmed. Check activity before retrying.';}
      finally{busy=false;await refreshChatActivity();renderRoutines();}
    });controls.append(run);
    const edit=document.createElement('button');edit.type='button';edit.className='secondary';edit.textContent='Edit';edit.addEventListener('click',()=>{if(dirty){showError('Save or cancel your current edit first.');return;}editRoutine(item);});controls.append(edit);
    const remove=document.createElement('button');remove.type='button';remove.className='quiet';remove.textContent='Delete';remove.addEventListener('click',async()=>{if(!confirm(`Delete routine “${item.name}”?`))return;try{await api(`/v1/routines/${item.id}`,'DELETE',{revision:item.revision});await loadRoutines();}catch(error){showError(error.message);}});controls.append(remove);card.append(controls);
    if(!ready){const note=document.createElement('p');note.className='hint';note.textContent='Run needs available devices with Control permission. Review Devices to enable them.';card.append(note);}list.append(card);
  }
}
async function loadRoutines() {
  const data=await api('/v1/routines');routineItems=data.items;
  try {routineDevices=(await api('/v1/home/devices')).devices;$('routine-devices-note').textContent='Routines are encrypted on your host. No schedule runs them automatically.';}
  catch {routineDevices=[];$('routine-devices-note').textContent='Home Assistant is unavailable. Saved routines are still here to inspect; running them needs a connection.';}
  renderRoutines();
}
$('routine-name').addEventListener('input',routineChanged);
$('routine-new').addEventListener('click',()=>{if(dirty){showError('Save or cancel your edit first.');return;}editRoutine();});
$('routine-refresh').addEventListener('click',async()=>{if(dirty){showError('Save or cancel your edit first.');return;}try{await loadRoutines();}catch(error){showError(error.message);}});
$('routine-add').addEventListener('click',()=>{if(routineDraft.length>=12)return;routineDraft.push({entity_id:'',action:'',value:null,unit:null});routineChanged();renderRoutineSteps();});
$('routine-cancel').addEventListener('click',()=>{dirty=false;routineEditing=null;$('routine-form').classList.add('hidden');});
$('routine-form').addEventListener('submit',async event=>{
  event.preventDefault();$('routine-save').disabled=true;showError('');
  const body={name:$('routine-name').value.trim(),steps:routineDraft};if(routineEditing)body.revision=routineEditing.revision;
  try{await api(routineEditing?`/v1/routines/${routineEditing.id}`:'/v1/routines',routineEditing?'PUT':'POST',body);dirty=false;routineEditing=null;$('routine-form').classList.add('hidden');$('routine-result').textContent='Routine saved and ready to review.';await loadRoutines();}
  catch(error){showError(error.message);}
  finally{$('routine-save').disabled=false;}
});

let taskItems=[], taskPolling=false;
async function loadTasks() {
  if(taskPolling)return;taskPolling=true;
  try {
    taskItems=(await api('/v1/tasks')).items;$('task-list').replaceChildren();
    $('task-start').disabled=taskItems.some(t=>t.active);
    if(!taskItems.length){const p=document.createElement('p');p.className='notice';p.textContent='Your research reports will appear here, with their sources.';$('task-list').append(p);}
    for(const task of taskItems) {
      const card=document.createElement('article');card.className='task-card';
      const title=document.createElement('h3');title.textContent=task.title;
      const status=document.createElement('p');status.className='provider-badge';status.textContent=task.state==='completed'?'Research complete':task.caption;
      const actions=document.createElement('div');actions.className='actions';
      const stop=document.createElement('button');stop.className='secondary';stop.textContent=task.active?'Stop research':'Delete';stop.disabled=task.cancel_requested && task.active;
      stop.addEventListener('click',async()=>{stop.disabled=true;try{await api(`/v1/tasks/${task.id}`+(task.active?'/stop':''),task.active?'POST':'DELETE');await loadTasks();}catch(error){showError(error.message);stop.disabled=false;}});actions.append(stop);
      card.append(title,status);
      if(task.result){
        const report=document.createElement('div');report.className='task-report';report.textContent=task.result.display_text || task.result.text;card.append(report);
        const sources=document.createElement('ol');sources.className='task-sources';
        for(const source of task.result.sources || []){const row=document.createElement('li');const link=document.createElement('a');link.textContent=source.title;link.href=source.url;link.target='_blank';link.rel='noopener noreferrer';row.append(link);sources.append(row);}card.append(sources);
        if(task.state==='completed'){
          const download=document.createElement('button');download.className='secondary';download.textContent='Download report';
          download.addEventListener('click',()=>{const text='# '+task.title+'\n\n'+(task.result.display_text || task.result.text)+'\n\n'+(task.result.sources || []).map((s,i)=>`[${i+1}] ${s.title}: ${s.url}`).join('\n');const url=URL.createObjectURL(new Blob([text],{type:'text/markdown'}));const link=document.createElement('a');link.href=url;link.download='echo-research.md';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});actions.append(download);
        }
      }
      card.append(actions);$('task-list').append(card);
    }
  } finally {taskPolling=false;}
}
$('task-form').addEventListener('submit',async event=>{event.preventDefault();$('task-start').disabled=true;showError('');try{await api('/v1/tasks','POST',{prompt:$('task-prompt').value.trim()});$('task-prompt').value='';await loadTasks();}catch(error){showError(error.message);$('task-start').disabled=false;}});
$('tasks-refresh').addEventListener('click',()=>loadTasks().catch(error=>showError(error.message)));
setInterval(()=>{if(tasksPage && authenticated && taskItems.some(t=>t.active))loadTasks().catch(()=>{});},2000);

async function start() {
  $(tasksPage ? 'tasks-tab' : routinesPage ? 'routines-tab' : devicesPage ? 'devices-tab' : memoryPage ? 'memory-tab' : settingsPage ? 'settings-tab' : 'chat-tab').classList.add('active');
  const ticket = new URLSearchParams(location.hash.slice(1)).get('ticket');
  if (location.hash) history.replaceState(null,'',location.pathname);
  try {
    if (ticket) await api('/v1/ui/session','POST',{ticket});
    state = await api('/v1/settings'); authenticated = true;
    $('locked').classList.add('hidden'); showError('');
    $('logout').classList.remove('hidden'); $(activePanel).classList.remove('hidden');
    if (settingsPage) {
      const speech = await api('/v1/settings/speech'); $('stt-engine').replaceChildren();
      for (const engine of speech.stt) {const option = document.createElement('option'); option.value = engine.id; option.textContent = engine.name + (engine.available ? '' : ' · not installed'); option.disabled = !engine.available; $('stt-engine').append(option);}
      speechEngines = speech.engines; $('tts-engine').replaceChildren();
      for (const engine of speechEngines) {const option = document.createElement('option'); option.value = engine.id; option.textContent = engine.name + (engine.available ? '' : ' · not installed'); option.disabled = !engine.available; $('tts-engine').append(option);}
      $('speech-note').textContent = `Active recognition: ${speech.active_stt}. Voice and pace apply to the next reply. Recognition changes require a bridge restart. Saving never changes volume or plays audio.`;
    }
    fillSettings(state);
    if (tasksPage) await loadTasks();
    else if (routinesPage) {
      $('routines-panel').append($('chat-activity'));
      try { await loadRoutines(); } catch(error) { showError(error.message); }
    }
    else if (devicesPage) {
      homeEditing(false);
      try {await loadDevices();} catch(error) {$('home-summary').textContent='Device inventory unavailable';showError(error.message);}
    }
    else if (memoryPage) await loadMemories();
    else if (!settingsPage) { const chat = await api('/v1/chat'); $('messages').replaceChildren(); for (const message of chat.messages) addMessage(message.role,message.display_text || message.content,false,message.sources,message.looked_up,message.home_actions); }
  } catch(error) {lock(); showError(error.message);}
  await refreshStatus();
  await refreshChatActivity();
}
// A launcher may navigate the current tab to the same path with a new fragment.
// Serialize bootstrap requests and keep just one status timer across sign-ins.
let startQueue = Promise.resolve();
const requestStart = () => { startQueue = startQueue.then(start); };
window.addEventListener('hashchange', () => {
  if (new URLSearchParams(location.hash.slice(1)).has('ticket')) requestStart();
});
requestStart();
setInterval(refreshStatus, 5000);
setInterval(refreshChatActivity, 1000);

setInterval(()=>{if(devicesPage && authenticated && !dirty && !roomRequest)loadRoomCards().catch(()=>{});},5000);

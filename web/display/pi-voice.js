/* Native Pi wake state. Recordings and reply audio never enter this page. */
'use strict';
endpoints.piVoice='/v1/display/local-voice';
const piVoiceCard=document.createElement('article');piVoiceCard.className='card';piVoiceCard.style.marginTop='16px';
piVoiceCard.innerHTML='<span class="eyebrow">THIS DEVICE</span><h2>Talk to this Pi.</h2><p class="soft" id="pi-voice-status">Checking the local listener…</p><form id="pi-voice-form" hidden><label>Attached microphone<select id="pi-voice-input" required></select></label><label>Attached speaker<select id="pi-voice-output" required></select></label><label>Voice output level <output id="pi-voice-level">2%</output><input type="range" id="pi-voice-volume" min="0" max="30" value="2"></label><label class="check-label"><input type="checkbox" id="pi-voice-enabled">Enable the local wake listener</label><label>When Echo wakes during music<select id="pi-voice-music-mode"><option value="pause">Pause music</option><option value="duck">Lower music by 80% (shared audio output)</option></select></label><label class="check-label"><input type="checkbox" id="pi-voice-aec">Interrupt spoken replies by voice (requires an echo-cancelled input)</label><label class="check-label"><input type="checkbox" id="pi-voice-home">Allow spoken requests to use granted home controls</label><button type="submit" class="pill primary">Save Pi voice</button><p class="tiny soft">Say “Hey Echo” or “Okay Echo,” wait for the soft cue, then speak. Wake detection stays on this Pi; only your command goes to the private speech host. Wake words work during music. Lowering music needs a shared audio output for Spotify and Echo. Speaker audio can cause false wakes without echo cancellation. Use Talk or Stop to interrupt a spoken reply when echo cancellation is unavailable. Microphone mute here is software mute.</p></form>';
$('page-settings').append(piVoiceCard);
const voiceDiagnostics=document.createElement('details');voiceDiagnostics.id='pi-voice-diagnostics';voiceDiagnostics.hidden=true;
voiceDiagnostics.innerHTML='<summary>Voice troubleshooting</summary><p id="pi-input-level" class="soft"></p><meter id="pi-input-meter" min="-90" max="0" low="-55" high="-5" optimum="-20" value="-90" aria-label="Microphone input level"></meter><p id="pi-input-measurement" class="tiny soft"></p><ol id="pi-voice-events" class="tiny soft"></ol><p class="tiny soft">Stages and input levels stay in memory for up to 15 minutes, then disappear. No recordings or background speech are saved here.</p><button id="pi-clear-diagnostics" type="button" class="pill">Clear troubleshooting history</button>';
piVoiceCard.append(voiceDiagnostics);
$('pi-clear-diagnostics').onclick=()=>piVoiceControl('clear_diagnostics');
function renderVoiceDiagnostics(state){
  const d=state?.diagnostics;voiceDiagnostics.hidden=!d;
  if(!d)return;
  const live=d.frame_age_seconds!==null&&d.frame_age_seconds<2;
  $('pi-input-level').textContent=!live?'Microphone is not sending samples.':d.recent_rms_dbfs<-65?'Microphone signal is almost silent. Check its physical mute switch.':d.recent_rms_dbfs<-48?'Microphone input is quiet. Speak closer to the microphone.':'Microphone audio is arriving.';
  $('pi-input-meter').value=live&&d.level_dbfs!==null?d.level_dbfs:-90;
  $('pi-input-measurement').textContent=live?`Input ${d.level_dbfs} dBFS · recent peak ${d.recent_peak_dbfs} dBFS`:'';
  const labels={wake_detected:'Wake word detected',talk_pressed:'Talk button pressed',cue_started:'Playing the listening cue',cue_finished:'Listening cue finished',capture_started:'Listening for your request',capture_finished:'Microphone capture ended',no_speech:'No usable speech after the cue',request_sent:'Request sent for transcription and reply',reply_received:'Reply received',reply_playing:'Playing the reply',reply_finished:'Reply playback finished',reply_audio_failed:'Reply audio failed',transcription_empty:'Speech could not be transcribed',interrupted:'Request stopped or microphone handed over',request_failed:'Speech host request failed',playback_failed:'Speaker playback failed',microphone_or_host_unavailable:'Microphone or speech host unavailable'};
  $('pi-voice-events').replaceChildren(...(d.events||[]).slice(-10).reverse().map(e=>{
    const li=document.createElement('li');const details=e.voiced_ms!==undefined?` · ${(e.voiced_ms/1000).toFixed(1)} seconds of detected speech`:e.http_status?` · HTTP ${e.http_status}`:'';
    li.textContent=`${labels[e.stage]||'Voice event'}${details} · ${Math.round(e.age_seconds)} seconds ago`;return li;
  }));
  if(!d.events?.length){const li=document.createElement('li');li.textContent='No wake or Talk attempts since the listener started, or history expired.';$('pi-voice-events').append(li);}
}
const piMute=document.createElement('button');piMute.id='pi-voice-mute';piMute.type='button';piMute.className='pill';piMute.hidden=true;$('wake-word-status').after(piMute);
let piVoiceSignature='',piVoicePolling=false,lastPiReply=null;
function piVoiceEnabled(){return data.piVoice?.supported&&data.piVoice.settings.enabled;}
function piVoiceBusy(){return piVoiceEnabled()&&['opening','cue','listening','thinking','speaking','stopping'].includes(data.piVoice.phase);}
function piVoiceWakeCaption(){const phase=data.piVoice?.phase;return phase==='muted'?'Microphone muted on this Pi':phase==='playback_guard'?'Wake paused during playback · tap Talk':phase==='unavailable'?'Pi microphone or speech service unavailable':'Hey Echo · Okay Echo';}
function piVoicePresence(){
  if(!piVoiceEnabled())return null;
  if(!fresh('piVoice'))return {state:'disconnected',detail:['Reconnecting to this Pi…','The local listener is unavailable. Microphone settings are preserved.']};
  const phases={armed:['ready',['Ready when you are.','Say “Hey Echo” or “Okay Echo.”']],muted:['muted',['A little quiet.','This Pi’s microphone is software-muted.']],cue:['listening',['Go ahead.','Wait for the soft cue, then speak.']],listening:['listening',['I’m listening.','Speak naturally. I’ll send it after a pause.']],thinking:['thinking',['On it.','Thinking about your request.']],speaking:['speaking',['Here’s what I found.','Replying through this Pi’s speaker.']],stopping:['stopping',['Stopping…','Closing this voice request.']],busy:['ready',['One thing at a time.','The microphone is in use by another audio session.']],playback_guard:['ready',['Enjoy the music.','Tap Talk to pause playback and ask Echo.']],unavailable:['disconnected',['Voice needs attention.',data.piVoice.error||'Check the attached microphone and speaker.']]};
  const phase=phases[data.piVoice.phase];return phase?{state:phase[0],detail:phase[1]}:null;
}
async function refreshPiVoice(){
  if(piVoicePolling)return;piVoicePolling=true;
  try{data.piVoice=await api('/v1/display/local-voice',undefined,'GET',AbortSignal.timeout(4000));received.piVoice=Date.now();renderPiVoice();voiceButtons();}
  catch{delete received.piVoice;renderPiVoice();voiceButtons();}
  finally{piVoicePolling=false;}
}
async function piVoiceControl(action){const body={action};if(action==='talk'){body.allow_home=$('allow-home').checked;body.reply_audio=$('voice-speak').checked;$('allow-home').checked=false;}try{await api('/v1/display/local-voice',body);await refreshPiVoice();}catch(error){toast(error.message);}}
async function piVoiceVolume(volume){try{await api('/v1/display/local-voice',{...data.piVoice.settings,volume},'PUT');await refreshPiVoice();}catch(error){toast(error.message);}}
function renderPiVoice(){
  const state=data.piVoice,supported=!!state?.supported;
  renderVoiceDiagnostics(fresh('piVoice')?state:null);
  $('pi-voice-form').hidden=!supported;piMute.hidden=!supported||!state.settings.enabled;
  $('pi-voice-status').textContent=!fresh('piVoice')?'Local listener is unavailable.':!supported?'Native wake setup is available on a paired Pi bridge.':!state.runtime_installed?'Install the Pi wake runtime before enabling the listener.':state.error||`Microphone ${human(state.phase)}.`;
  if(!supported)return;
  piMute.textContent=state.settings.muted?'Unmute this Pi':'Mute this Pi';piMute.setAttribute('aria-pressed',String(state.settings.muted));
  const signature=JSON.stringify([state.settings,state.inputs,state.outputs]);
  if(signature!==piVoiceSignature&&!$('pi-voice-form').contains(document.activeElement)){
    piVoiceSignature=signature;
    for(const key of ['input','output']){const items=state[key==='input'?'inputs':'outputs']||[],select=$('pi-voice-'+key);select.innerHTML='<option value="">Choose an attached device</option>'+items.map(i=>`<option value="${esc(i.id)}">${esc(i.name)}</option>`).join('');if(state.settings[key]&&!items.some(i=>i.id===state.settings[key]))select.insertAdjacentHTML('beforeend',`<option value="${esc(state.settings[key])}">${esc(state.settings[key])} · unavailable</option>`);select.value=state.settings[key];}
    $('pi-voice-enabled').checked=state.settings.enabled;$('pi-voice-aec').checked=state.settings.echo_cancelled_input;$('pi-voice-home').checked=state.settings.allow_home;
    $('pi-voice-music-mode').value=state.settings.music_mode||'pause';$('pi-voice-volume').value=state.settings.volume;$('pi-voice-level').textContent=state.settings.volume+'%';
    if(state.settings.enabled){$('voice-volume').value=state.settings.volume;$('voice-volume-label').textContent=state.settings.volume+'%';}
  }
  if(state.result&&state.result.id!==lastPiReply){lastPiReply=state.result.id;const user=appendChatMessage('user',state.result.transcript||'Voice message'),answer=appendChatMessage('assistant','',true);finishChatMessage(answer,state.result);}
  const privacy=$('voice-privacy-note');if(privacy)privacy.textContent=piVoiceEnabled()?'Wake detection stays on this Pi; software mute closes its microphone.':'Mic closes before processing · messages stay in this tab until reload';
  if(piVoiceEnabled())$('display-voice-status').textContent=state.error||piVoicePresence()?.detail[1]||'Pi listener ready.';
}
extensions.push(renderPiVoice);setInterval(()=>{if(data.piVoice?.supported)void refreshPiVoice();},1000);
$('pi-voice-volume').oninput=()=>{$('pi-voice-level').textContent=$('pi-voice-volume').value+'%';};
$('pi-voice-form').onsubmit=event=>{event.preventDefault();void action(()=>api('/v1/display/local-voice',{enabled:$('pi-voice-enabled').checked,muted:data.piVoice.settings.muted,input:$('pi-voice-input').value,output:$('pi-voice-output').value,volume:Number($('pi-voice-volume').value),echo_cancelled_input:$('pi-voice-aec').checked,music_mode:$('pi-voice-music-mode').value,allow_home:$('pi-voice-home').checked},'PUT'),'Pi voice settings saved. Use Unmute this Pi when ready to listen.');};
piMute.onclick=()=>piVoiceControl(data.piVoice.settings.muted?'unmute':'mute');

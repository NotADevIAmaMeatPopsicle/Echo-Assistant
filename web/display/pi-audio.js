/* Local Pi receiver controls. Other screens keep an explicit unsupported state. */
'use strict';
endpoints.piAudio='/v1/display/music/settings';
const piAudioCard=document.createElement('article');piAudioCard.className='card';piAudioCard.style.marginTop='16px';
piAudioCard.innerHTML='<span class="eyebrow">THIS DEVICE</span><h2>Spotify on this Pi.</h2><p class="soft" id="pi-audio-status">Checking the local audio adapter…</p><form id="pi-audio-form" hidden><label>Spotify device name<input id="pi-receiver-name" maxlength="60" value="Echo Display" required></label><label>Attached speaker / audio output<select id="pi-output" required></select></label><label>Output volume <output id="pi-output-level">2%</output><input id="pi-output-volume" type="range" min="0" max="30" value="2"></label><label class="check-label"><input id="pi-receiver-enabled" type="checkbox">Enable this Spotify receiver</label><button class="pill primary" type="submit">Save receiver</button><p class="tiny soft">Choose the speaker attached to this Pi. Changing its output or name restarts this receiver. Voice and calls pause music; press Play to resume.</p></form>';
$('page-settings').append(piAudioCard);
let piAudioSignature='',piFocusPending=null,piFocusDesired=false;const piAudioClient=crypto.randomUUID().replaceAll('-','');
function localAudioBusy(){const browserVoice=typeof micStream!=='undefined'&&(micOpening||voiceCancelling||!!micStream||!!voiceRequest||!voicePlayer.paused);return browserVoice||!player.paused||typeof announceCurrent!=='undefined'&&!!announceCurrent||typeof intercomIsBusy==='function'&&intercomIsBusy();}
function piFocusSend(busy){
  if(!data.piAudio?.supported)return Promise.resolve();
  piFocusDesired=busy;
  if(piFocusPending)return piFocusPending;
  piFocusPending=(async()=>{let sent;do{sent=piFocusDesired;await api('/v1/display/music/focus',{client:piAudioClient,busy:sent});}while(sent!==piFocusDesired);})().finally(()=>{piFocusPending=null;});
  return piFocusPending;
}
async function prepareLocalAudio(){if(!fresh('piAudio')){data.piAudio=await api('/v1/display/music/settings');received.piAudio=Date.now();}await piFocusSend(true);}
function refreshPiFocus(){void piFocusSend(!document.hidden&&localAudioBusy()).catch(()=>{});}
document.addEventListener('echo:audio-focus',refreshPiFocus);
document.addEventListener('visibilitychange',refreshPiFocus);
window.addEventListener('DOMContentLoaded',()=>{player.addEventListener('play',refreshPiFocus);player.addEventListener('pause',refreshPiFocus);player.addEventListener('ended',refreshPiFocus);});
setInterval(refreshPiFocus,5000);
extensions.push(()=>{
  const state=data.piAudio,supported=!!state?.supported;
  $('pi-audio-form').hidden=!supported;
  $('pi-audio-status').textContent=!fresh('piAudio')?'Local audio adapter unavailable.':!supported?'Pi receiver setup is available through an installed Pi display bridge.':!state.runtime_installed?'Install the Pi receiver runtime before enabling it.':state.error||`Receiver ${human(state.status)}. Audio uses this Pi.`;
  if(!supported)return;
  const signature=JSON.stringify([state.settings,state.outputs,state.runtime_installed]);if(signature===piAudioSignature)return;piAudioSignature=signature;
  $('pi-receiver-name').value=state.settings.name;$('pi-output-volume').value=state.settings.volume;$('pi-output-level').textContent=state.settings.volume+'%';$('pi-receiver-enabled').checked=state.settings.enabled;
  const items=state.outputs||[];$('pi-output').innerHTML='<option value="">Choose an attached output</option>'+items.map(o=>`<option value="${esc(o.id)}">${esc(o.name)} · ${esc(o.id)}</option>`).join('');
  if(state.settings.output&&!items.some(o=>o.id===state.settings.output))$('pi-output').insertAdjacentHTML('beforeend',`<option value="${esc(state.settings.output)}">${esc(state.settings.output)} · unavailable</option>`);
  $('pi-output').value=state.settings.output;$('pi-receiver-enabled').disabled=!state.runtime_installed;
});
$('pi-output-volume').oninput=()=>{$('pi-output-level').textContent=$('pi-output-volume').value+'%';};
$('pi-audio-form').onsubmit=event=>{event.preventDefault();void action(()=>api('/v1/display/music/settings',{enabled:$('pi-receiver-enabled').checked,name:$('pi-receiver-name').value.trim(),output:$('pi-output').value,volume:Number($('pi-output-volume').value)},'PUT'),'Pi receiver settings saved.');};

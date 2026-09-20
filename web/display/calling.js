/* Explicit browser calls through an owner-configured provider. No recording. */
'use strict';
let echoCallBusy=false;
function externalCallBusy(){return echoCallBusy;}
(()=>{
  endpoints.calling='/v1/calling';
  const client=crypto.randomUUID().replaceAll('-','');
  const tab=document.createElement('button');tab.id='room-tab-calling';tab.type='button';tab.textContent='Voice & video';callTab.append(tab);
  const panel=document.createElement('article');panel.id='calling-panel';panel.className='card calling-card';panel.hidden=true;
  panel.innerHTML=`<div class="calling-stage"><div class="orb" id="calling-orb" data-state="disconnected"><div class="orb-core"></div></div><span class="eyebrow">VOICE & VIDEO CALLS</span><h2 id="calling-heading">A little closer, wherever you are.</h2><p class="soft" id="calling-status" role="status">Checking calling…</p><div id="calling-remote" class="calling-video"></div><div id="calling-local" class="calling-video"></div><div id="calling-remote-audio"></div><div id="calling-controls" class="row wrap calling-controls" hidden><button type="button" class="pill" id="calling-mute">Mute microphone</button><button type="button" class="pill" id="calling-camera">Turn camera on</button><button type="button" class="pill call-end" id="calling-end">Hang up</button></div><button type="button" class="pill" id="calling-unlock" hidden>Enable call sound</button><label>Call volume <output id="calling-level">2%</output><input id="calling-volume" aria-label="Call volume" type="range" min="0" max="30" value="2"></label></div><div><div id="calling-start-options"><h3>Start a conversation</h3><p class="soft">Share a code with someone who can already open your private Echo UI.</p><button class="pill primary" id="calling-start" type="button">Start voice call</button><form id="calling-join-form"><label>Invitation code<input type="text" id="calling-invite" maxlength="40" autocomplete="off" autocapitalize="none" spellcheck="false" placeholder="Paste the code here" required></label><button class="pill" id="calling-join" type="submit">Join call</button></form></div><div id="calling-invitation" hidden><h3>Invite someone</h3><code id="calling-code"></code><button class="pill" id="calling-copy" type="button">Copy code</button><p class="tiny soft" id="calling-expiry"></p></div><p class="tiny soft calling-help">Microphone starts only when you start or join. Camera is off until you turn it on. Calls use your configured LiveKit server, with no Echo recording or transcription. Keep this page open; calls last up to 15 minutes.</p><p class="tiny soft">This does not open your private network to visitors. Both people need existing Echo access. It does not call telephone numbers.</p></div>`;
  $('page-audio').append(panel);
  $('page-audio').querySelector('.section-head p').textContent='Announcements, room intercom, and voice or video calls.';
  const previousTab=roomAudioTab;
  roomAudioTab=function(intercom){panel.hidden=true;tab.classList.remove('selected');previousTab(intercom);if(echoCallBusy)void endCall('Call ended when you left the calling page.');};
  tab.onclick=()=>{previousTab(false);$('page-audio').querySelector('.room-audio-grid').hidden=true;intercomPanel.hidden=true;$('room-tab-announcements').classList.remove('selected');panel.hidden=false;tab.classList.add('selected');};
  const settings=document.createElement('article');settings.className='card calling-settings';settings.id='calling-settings';settings.hidden=true;
  settings.innerHTML=`<span class="eyebrow">OPTIONAL CALLING</span><h2>Bring your own calling server.</h2><p class="soft">Use LiveKit Cloud or a self-hosted LiveKit server. Only the selected Household displays and the owner workspace can place or join calls.</p><button type="button" class="pill" id="calling-configure">Configure calls</button><form id="calling-config-form" hidden><label class="check-label"><input type="checkbox" id="calling-enabled">Enable voice and video calling</label><label>LiveKit WSS server<input id="calling-url" type="text" autocomplete="off" placeholder="wss://calls.example.com"></label><div class="calling-fields"><label>API key<input id="calling-key" type="password" autocomplete="new-password" placeholder="Leave blank to keep saved"></label><label>API secret<input id="calling-secret" type="password" autocomplete="new-password" placeholder="Leave blank to keep saved"></label></div><label class="check-label"><input type="checkbox" id="calling-clear">Remove saved credentials (turn calling off first)</label><h3>Allowed displays</h3><div id="calling-permissions"></div><p class="tiny soft">Keys are encrypted on the Echo host and never returned to a display. Calls may use the provider’s internet relays. Provider fees and server networking are managed separately.</p><button class="pill primary" type="submit">Save calling</button><p id="calling-config-status" class="soft" role="status"></p><button class="pill" type="button" id="calling-reload" hidden>Reload display</button></form>`;
  $('page-settings').append(settings);
  let config=null,room=null,session=null,epoch=0,access=null,opening=false,operation=false,pulsing=false,message='',deadline=null;
  const local=new Set(),remote=new Set();
  function changed(){document.dispatchEvent(new Event('echo:intercom'));document.dispatchEvent(new Event('echo:audio-focus'));render();}
  function busyElsewhere(){return icOpening||!!icCall&&icCall.status!=='ended'||micOpening||!!micStream||!!voiceRequest||!!chatAbort||!voicePlayer.paused||!player.paused||!!announceCurrent;}
  function render(){
    const available=fresh('calling')&&data.calling?.enabled&&data.calling.allowed&&!signInRequired;
    $('calling-start').disabled=$('calling-join').disabled=echoCallBusy||!available||busyElsewhere();
    $('calling-controls').hidden=!echoCallBusy;$('calling-start-options').hidden=echoCallBusy;
    $('calling-mute').disabled=$('calling-camera').disabled=opening||operation||!room;
    $('calling-mute').textContent=[...local].some(t=>t.kind==='audio')?'Mute microphone':'Unmute microphone';
    $('calling-camera').textContent=[...local].some(t=>t.kind==='video')?'Turn camera off':'Turn camera on';
    $('calling-orb').dataset.state=echoCallBusy?(opening?'thinking':'listening'):'disconnected';
    $('calling-heading').textContent=echoCallBusy?(opening?'Connecting…':'Your call. Your space.'):'A little closer, wherever you are.';
    $('calling-status').textContent=message||(!fresh('calling')?'Checking calling…':!data.calling.enabled?'Calling is off. Configure a LiveKit server in Settings.':!data.calling.allowed?'Ask the owner to allow calling on this Household display.':'Ready. Start a call or enter an invitation code.');
    settings.hidden=data.session?.role!=='owner';
  }
  function version(){return (data.session?.receiver_id||'owner')+':'+(data.session?.profile_revision||0);}
  function current(mark,r){return epoch===mark&&room===r&&echoCallBusy&&!document.hidden&&access===version();}
  function stopLocal(track){track.stop();local.delete(track);for(const el of track.detach())el.remove();}
  async function capture(kind,mark,r){
    const t=kind==='audio'?await LivekitClient.createLocalAudioTrack({echoCancellation:true,noiseSuppression:true,autoGainControl:true}):await LivekitClient.createLocalVideoTrack({resolution:{width:640,height:360,frameRate:20}});
    if(!current(mark,r)){t.stop();return;}
    local.add(t);
    try{await r.localParticipant.publishTrack(t);if(!current(mark,r)){stopLocal(t);return;}if(kind==='video'){const el=t.attach();el.muted=true;el.playsInline=true;$('calling-local').append(el);}}
    catch(error){stopLocal(t);throw error;}
    changed();
  }
  function subscription(track,mark,r){
    if(!current(mark,r))return;
    remote.add(track);
    if(track.kind==='audio')track.setVolume(Number($('calling-volume').value)/100);
    const element=track.attach();
    if(track.kind==='audio'){element.volume=Number($('calling-volume').value)/100;$('calling-remote-audio').append(element);}
    else{element.playsInline=true;$('calling-remote').append(element);}
  }
  async function endCall(reason='Call ended.'){
    ++epoch;clearTimeout(deadline);deadline=null;const old=session,r=room;session=null;room=null;opening=false;operation=false;
    for(const t of [...local])stopLocal(t);
    for(const t of remote)for(const el of t.detach())el.remove();remote.clear();
    // Disconnect closes transport and also catches SDK-owned tracks.
    if(r)void r.disconnect(true).catch(()=>{});
    echoCallBusy=false;message=reason;$('calling-code').textContent='';$('calling-invitation').hidden=true;$('calling-unlock').hidden=true;changed();
    if(old)try{await api('/v1/calling/'+old.id+'/end',{client});}catch{message=reason+' Server cleanup is pending; your microphone and camera are closed.';render();}
  }
  async function begin(code){
    if(echoCallBusy||busyElsewhere()||!fresh('calling')||!data.calling?.enabled||!data.calling.allowed)return;
    if(data.health?.display_demo){toast('This preview never opens a real call or microphone.');return;}
    const mark=++epoch;access=version();echoCallBusy=true;opening=true;message='Preparing this device…';changed();
    try{
      if(typeof prepareLocalAudio==='function')await prepareLocalAudio();
      if(mark!==epoch||document.hidden||access!==version())return;
      const result=await api('/v1/calling/'+(code?'join':'start'),{client,...(code?{code}:{})});
      if(mark!==epoch||document.hidden||access!==version()){void api('/v1/calling/'+result.id+'/end',{client}).catch(()=>{});return;}
      session=result;$('calling-invite').value='';
      deadline=setTimeout(()=>void endCall('Call time limit reached.'),Math.max(0,result.expires_at*1000-Date.now()));
      if(result.code){$('calling-code').textContent=result.code.match(/.{8}/g).join(' ');$('calling-expiry').textContent='Use once within two minutes. On the other Echo screen, open Room audio → Voice & video → Join call.';$('calling-invitation').hidden=false;}
      const r=new LivekitClient.Room({adaptiveStream:true,dynacast:true});room=r;
      r.on(LivekitClient.RoomEvent.TrackSubscribed,t=>subscription(t,mark,r));
      r.on(LivekitClient.RoomEvent.TrackUnsubscribed,t=>{remote.delete(t);for(const el of t.detach())el.remove();});
      r.on(LivekitClient.RoomEvent.Disconnected,()=>{if(current(mark,r))void endCall('Connection ended.');});
      r.on(LivekitClient.RoomEvent.Reconnecting,()=>{if(current(mark,r)){message='Reconnecting…';render();}});
      r.on(LivekitClient.RoomEvent.Reconnected,()=>{if(current(mark,r)){message='Connected. Microphone controls are below.';render();}});
      r.on(LivekitClient.RoomEvent.ParticipantConnected,()=>{if(current(mark,r)){message='Connected. Your guest is here.';$('calling-code').textContent='';$('calling-invitation').hidden=true;render();}});
      r.on(LivekitClient.RoomEvent.ParticipantDisconnected,()=>{if(current(mark,r))void endCall('The other person left.');});
      r.on(LivekitClient.RoomEvent.AudioPlaybackStatusChanged,()=>{$('calling-unlock').hidden=r.canPlaybackAudio;});
      await r.connect(result.url,result.token,{autoSubscribe:true});delete result.token;
      if(!current(mark,r)){void r.disconnect(true);return;}
      await capture('audio',mark,r);
      if(!current(mark,r))return;
      opening=false;message=code?'Connected. Your microphone is on.':'Waiting for your guest. Your microphone is on.';changed();
    }catch(error){if(mark===epoch)await endCall(error?.name==='NotAllowedError'?'Microphone permission was not granted.':'Could not connect. Check the calling server, network and microphone permission.');}
  }
  $('calling-start').onclick=()=>void begin();
  $('calling-join-form').onsubmit=e=>{e.preventDefault();const code=$('calling-invite').value.replace(/[\s-]/g,'').toLowerCase();if(!/^[a-f0-9]{32}$/.test(code)){toast('Paste a complete invitation code.');return;}void begin(code);};
  $('calling-end').onclick=()=>void endCall();
  async function toggle(kind){if(!room||opening||operation)return;const r=room,mark=epoch;operation=true;render();try{
    const track=[...local].find(t=>t.kind===kind);
    if(track){stopLocal(track);await r.localParticipant.unpublishTrack(track);}
    else await capture(kind,mark,r);
  }catch{message='Could not open that device. Check its permission and connection.';}finally{if(mark===epoch){operation=false;changed();}}}
  $('calling-mute').onclick=()=>void toggle('audio');$('calling-camera').onclick=()=>void toggle('video');
  $('calling-volume').oninput=()=>{const v=Number($('calling-volume').value)/100;$('calling-level').textContent=Math.round(v*100)+'%';for(const t of remote)if(t.kind==='audio')t.setVolume(v);};
  $('calling-copy').onclick=async()=>{try{await navigator.clipboard.writeText($('calling-code').textContent);toast('Invitation code copied.');}catch{toast('Select the invitation code to copy it.');}};
  $('calling-unlock').onclick=()=>{if(room)void room.startAudio().catch(()=>toast('Browser audio is still blocked.'));};
  async function pulse(){
    if(!session||pulsing)return;const mark=epoch,id=session.id;pulsing=true;
    try{await api('/v1/calling/'+id+'/pulse',{client});}catch{if(mark===epoch)await endCall('Lost private Echo access. Call closed.');}finally{pulsing=false;}
  }
  setInterval(()=>void pulse(),5000);
  document.addEventListener('visibilitychange',()=>{if(document.hidden&&echoCallBusy)void endCall('Call closed when this screen was hidden.');});
  window.addEventListener('pagehide',()=>{if(echoCallBusy)void endCall();});
  document.addEventListener('echo:page',event=>{if(event.detail!=='audio'&&echoCallBusy)void endCall('Call ended when you left the calling page.');});
  extensions.push(()=>{if(echoCallBusy&&(access!==version()||signInRequired||data.calling?.allowed===false||data.calling?.enabled===false))void endCall('Display access changed. Call closed.');render();});
  $('calling-configure').onclick=async()=>{try{
    config=await api('/v1/calling/settings');$('calling-config-form').hidden=false;$('calling-enabled').checked=config.enabled;$('calling-url').value=config.url;$('calling-clear').checked=false;
    $('calling-key').value=$('calling-secret').value='';$('calling-config-status').textContent=config.credentials_saved?'Credentials saved. Leave both fields blank to keep them.':'No credentials saved.';
    $('calling-permissions').innerHTML=config.displays.map(d=>`<label class="check-label"><input type="checkbox" value="${esc(d.id)}" ${config.allowed_displays.includes(d.id)?'checked':''}>${esc(d.name)}${d.profile?.mode==='guest'?' (Guest mode cannot call)':''}</label>`).join('')||'<p class="soft tiny">No paired displays yet. The owner workspace can still call.</p>';
  }catch{toast('Open the owner workspace to configure calls.');}};
  $('calling-config-form').onsubmit=async e=>{e.preventDefault();if(!config)return;const submit=e.submitter;submit.disabled=true;try{
    const next=await api('/v1/calling/settings',{revision:config.revision,enabled:$('calling-enabled').checked,url:$('calling-url').value.trim(),api_key:$('calling-key').value,api_secret:$('calling-secret').value,clear_credentials:$('calling-clear').checked,allowed_displays:[...$('calling-permissions input:checked')].map(e=>e.value)},'PUT');
    config={...config,...next};$('calling-key').value=$('calling-secret').value='';$('calling-config-status').textContent='Saved. Reload each calling display to apply the provider connection policy.';$('calling-reload').hidden=false;
  }catch(error){$('calling-config-status').textContent=error.message||'Could not save calling.';}finally{submit.disabled=false;}};
  $('calling-reload').onclick=()=>location.reload();
})();

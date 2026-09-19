/* Explicitly answered private room calls. No recordings or transcripts. */
'use strict';
const callTab=document.createElement('div');callTab.className='segmented room-audio-tabs';callTab.innerHTML='<button id="room-tab-announcements" class="selected" type="button">Announcements</button><button id="room-tab-intercom" type="button">Intercom</button>';
$('page-audio').insertBefore(callTab,$('page-audio').querySelector('.room-audio-grid'));
const intercomPanel=document.createElement('article');intercomPanel.id='intercom-panel';intercomPanel.className='card intercom-card';intercomPanel.hidden=true;
intercomPanel.innerHTML='<div class="intercom-presence"><div class="orb" id="intercom-orb" data-state="disconnected"><div class="orb-core"></div></div><span class="eyebrow">ROOM INTERCOM</span><h2 id="intercom-heading">A voice in the next room.</h2><p class="soft" id="intercom-status" role="status">Calls are off on this display.</p><button class="pill primary" id="intercom-enable" type="button">Enable calls here</button><div class="row wrap" id="intercom-controls" hidden><button class="pill primary" id="intercom-answer" type="button">Answer</button><button class="pill" id="intercom-mute" type="button" hidden>Mute microphone</button><button class="pill call-end" id="intercom-end" type="button">Decline</button></div><label id="intercom-volume-row">Call volume <output id="intercom-volume-label">2%</output><input id="intercom-volume" type="range" min="1" max="30" value="2"></label></div><div class="intercom-rooms"><h3>Call a room</h3><div id="intercom-rooms"></div><p class="tiny soft">Both rooms must enable calls. The other room chooses whether to answer. Audio stays on your private connection and is never recorded or transcribed.</p><p class="tiny soft">Keep this tab open. Calls end after a disconnect or 15 minutes.</p></div>';
$('page-audio').append(intercomPanel);
const intercomBanner=document.createElement('aside');intercomBanner.className='intercom-banner';intercomBanner.hidden=true;intercomBanner.innerHTML='<span class="eyebrow">ROOM CALL</span><h3 id="intercom-banner-name"></h3><p class="tiny soft">Your microphone stays closed until you answer.</p><button class="pill primary" id="intercom-banner-answer">Answer</button><button class="pill" id="intercom-banner-decline">Decline</button>';document.body.append(intercomBanner);
function roomAudioTab(intercom){intercomPanel.hidden=!intercom;$('page-audio').classList.toggle('is-intercom',intercom);$('page-audio').querySelector('.room-audio-grid').hidden=intercom;$('room-tab-intercom').classList.toggle('selected',intercom);$('room-tab-announcements').classList.toggle('selected',!intercom);document.querySelector('main').scrollTop=0;}
$('room-tab-announcements').onclick=()=>roomAudioTab(false);$('room-tab-intercom').onclick=()=>roomAudioTab(true);
const icClient=crypto.randomUUID().replaceAll('-','');
let icEnabled=false,icData=null,icCall=null,icPollBusy=false,icOperation=false,icOpening=false,icEpoch=0,icRevision=0,icStarting=false,icActiveId=null;
let icContext=null,icNode=null,icGain=null,icMic=null,icSource=null,icModule=false,icController=null,icQueue=[],icUploading=false,icSequence=0,icUploadGeneration=0,icError=null;
function intercomIsBusy(){return icOpening||!!icCall&&icCall.status!=='ended';}
function intercomExternalBusy(){return micOpening||!!micStream||!!voiceRequest||!!chatAbort||!voicePlayer.paused||!player.paused||!!announceCurrent;}
function icChanged(){document.dispatchEvent(new Event('echo:intercom'));renderIntercom();}
function renderIntercom(){
  const paired=!!data.session?.receiver_id,active=icCall?.status==='active',ringing=icCall?.status==='ringing';
  $('intercom-enable').hidden=ringing||active;$('intercom-enable').disabled=!paired||icOperation;
  $('intercom-enable').textContent=icEnabled?'Turn calls off':'Enable calls here';
  $('intercom-controls').hidden=!ringing&&!active&&!icOpening;
  $('intercom-answer').hidden=!ringing||icCall?.direction!=='incoming';$('intercom-answer').disabled=icOperation||intercomExternalBusy();
  $('intercom-mute').hidden=!active;$('intercom-mute').disabled=icOperation;$('intercom-mute').textContent=icMic?'Mute microphone':'Unmute microphone';
  $('intercom-end').textContent=active?'Hang up':icCall?.direction==='incoming'?'Decline':'Cancel call';
  $('intercom-heading').textContent=active?'With '+icCall.room:ringing?(icCall.direction==='incoming'?'Call from ':'Calling ')+icCall.room:'A voice in the next room.';
  $('intercom-orb').dataset.state=active?'listening':ringing?'thinking':'disconnected';
  if(!icOperation)$('intercom-status').textContent=!paired?'Use a paired display to make and receive calls.':active?`${icMic?'Microphone on':'Microphone muted'} · ${icCall.seconds||0}s${icCall.peer_muted?' · Other room muted':''}`:ringing?(icCall.direction==='incoming'?'Answer to open your microphone.':'Waiting for an answer. Audio is not being sent.') :icError?icError:icCall?.status==='ended'?'Call ended · '+human(icCall.reason):!icEnabled?'Calls are off on this display.':icData?.enabled?human(icData.status):'The owner needs to allow calls in Settings → Room receivers.';
  $('intercom-rooms').innerHTML=(icData?.rooms||[]).map(r=>`<button class="intercom-room" data-call-room="${esc(r.id)}" ${!icEnabled||!icData?.ready||!r.ready||icOperation?'disabled':''}><span><strong>${esc(r.room)}</strong><small>${esc(human(r.status))}</small></span><span>Call ↗</span></button>`).join('')||empty('Rooms appear here when the owner allows calls.');
  intercomBanner.hidden=!(ringing&&icCall.direction==='incoming');$('intercom-banner-name').textContent=icCall?.room||'';
  $('intercom-banner-answer').disabled=icOperation||intercomExternalBusy();
}
extensions.push(renderIntercom);
async function icRequest(action,body={},id=icCall?.id){return api('/v1/intercom/calls/'+id+'/'+action,{client:icClient,...body});}
function icStopMedia(){
  icEpoch++;icUploadGeneration++;icController?.abort();icController=null;icMic?.getTracks().forEach(t=>t.stop());icMic=null;icSource?.disconnect();icSource=null;
  if(icNode){icNode.port.onmessage=null;icNode.disconnect();icNode=null;}icGain?.disconnect();icGain=null;
  icQueue=[];icActiveId=null;icOpening=false;
}
async function icEnd(){
  const call=icCall;icRevision++;icStopMedia();if(call)icCall={...call,status:'ended',reason:'hangup'};icChanged();
  if(call&&call.status!=='ended')try{await icRequest('end',{},call.id);}catch{$('intercom-status').textContent='Microphone closed. The host could not confirm hang-up; the call expires when its connection drops.';icEnabled=false;}
}
async function icPrepareMic(epoch){
  if(typeof prepareLocalAudio==='function')await prepareLocalAudio();
  if(epoch!==icEpoch)throw Error('Call cancelled.');
  if(!navigator.mediaDevices?.getUserMedia)throw Error('A microphone and a secure browser connection are required.');
  icContext ||= new AudioContext();await icContext.resume();
  const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
  if(epoch!==icEpoch){stream.getTracks().forEach(t=>t.stop());throw Error('Call cancelled.');}
  icMic=stream;
  for(const track of stream.getTracks())track.addEventListener?.('ended',()=>{if(epoch===icEpoch&&icMic===stream)void icEnd();});
}
async function icSendAudio(epoch,id){
  if(icUploading)return;icUploading=true;const uploadGeneration=icUploadGeneration;
  try{
    while(epoch===icEpoch&&uploadGeneration===icUploadGeneration&&icQueue.length){
      const pcm=icQueue.shift(),sequence=icSequence++;
      const response=await fetch(`/v1/intercom/calls/${id}/audio?client=${icClient}&sequence=${sequence}`,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/octet-stream','X-Echo-Request':'1'},body:pcm,signal:AbortSignal.any([icController.signal,AbortSignal.timeout(2000)])});
      if(!response.ok)throw Error('Call upload stopped');
    }
  }catch{if(epoch===icEpoch&&uploadGeneration===icUploadGeneration)void icEnd();}
  finally{icUploading=false;}
}
async function icReadAudio(epoch,id){
  const response=await fetch(`/v1/intercom/calls/${id}/audio?client=${icClient}`,{credentials:'same-origin',cache:'no-store',signal:icController.signal});
  if(!response.ok||!response.body)throw Error('Call audio unavailable');
  const reader=response.body.getReader();let pending=new Uint8Array(),last=-1;
  try{
    while(epoch===icEpoch){
      const {value,done}=await reader.read();if(done)throw Error('Call stream ended');
      const joined=new Uint8Array(pending.length+value.length);joined.set(pending);joined.set(value,pending.length);pending=joined;
      if(pending.length>200000)throw Error('Call audio buffer exceeded its limit');
      while(pending.length>=8){
        const header=new DataView(pending.buffer,pending.byteOffset,8),sequence=header.getUint32(0,true),length=header.getUint32(4,true);
        if(length<640||length>6400||length%2)throw Error('Invalid call audio frame');
        if(pending.length<8+length)break;
        const frame=pending.slice(8,8+length);pending=pending.slice(8+length);
        if(sequence<=last)continue;if(last>=0&&sequence!==last+1)icNode?.port.postMessage({type:'clear'});last=sequence;
        icNode?.port.postMessage({type:'pcm',data:frame.buffer},[frame.buffer]);
      }
    }
  }finally{await reader.cancel().catch(()=>{});}
}
async function icStartMedia(){
  if(icStarting||!icCall||icCall.status!=='active'||icActiveId===icCall.id)return;
  icStarting=true;const epoch=icEpoch,id=icCall.id;
  try{
    if(!icMic||icContext?.state!=='running')throw Error('Microphone permission is required to answer.');
    if(!icModule){await icContext.audioWorklet.addModule('/assets/display/intercom-worklet.js');icModule=true;}
    if(epoch!==icEpoch)return;
    icNode=new AudioWorkletNode(icContext,'echo-intercom',{numberOfInputs:1,numberOfOutputs:1,outputChannelCount:[1]});
    icGain=icContext.createGain();icGain.gain.value=Number($('intercom-volume').value)/100;icNode.connect(icGain);icGain.connect(icContext.destination);
    icSource=icContext.createMediaStreamSource(icMic);icSource.connect(icNode);icController=new AbortController();icSequence=0;icActiveId=id;
    await icRequest('mute',{muted:false},id);if(epoch!==icEpoch)return;
    icNode.port.onmessage=event=>{if(epoch!==icEpoch||!icMic)return;icQueue.push(event.data.data);while(icQueue.length>3)icQueue.shift();void icSendAudio(epoch,id);};
    icNode.port.postMessage({type:'capture',enabled:true});
    void icReadAudio(epoch,id).catch(()=>{if(epoch===icEpoch)void icEnd();});
  }catch{if(epoch===icEpoch){await icEnd();icError='The call could not open its audio devices. Microphone closed.';}}
  finally{icStarting=false;icChanged();}
}
async function icPoll(){
  if(icPollBusy||!fresh('session')||!data.session?.receiver_id)return;
  icPollBusy=true;const revision=icRevision;
  try{
    const state=await api('/v1/intercom/heartbeat',{client:icClient,enabled:icEnabled&&!document.hidden,busy:intercomExternalBusy()});
    if(revision!==icRevision)return;icData=state;
    if(!icOperation){
      icCall=state.call;
      if(!icCall||icCall.status==='ended'){if(icMic||icActiveId)icStopMedia();}
      else if(icCall.status==='active')void icStartMedia();
    }
    icChanged();
  }catch{if(icCall&&icCall.status!=='ended'){icEnabled=false;void icEnd();}$('intercom-status').textContent='Call service unreachable. Microphone closed.';}
  finally{icPollBusy=false;}
}
async function icCallRoom(target){
  if(icOperation||intercomIsBusy())return;
  icOperation=true;icOpening=true;icError=null;icRevision++;const epoch=++icEpoch;icChanged();
  try{
    await icPrepareMic(epoch);if(epoch!==icEpoch)return;
    const call=await api('/v1/intercom/calls',{client:icClient,id:crypto.randomUUID().replaceAll('-',''),target,revision:icData.revision});
    if(epoch!==icEpoch){await icRequest('end',{},call.id);return;}icCall=call;
  }catch(error){icStopMedia();icError=error.message;}
  finally{icOperation=false;icOpening=false;icChanged();void icPoll();}
}
async function icAnswer(){
  if(icOperation||icCall?.status!=='ringing'||icCall.direction!=='incoming')return;
  icOperation=true;icOpening=true;icError=null;icRevision++;const epoch=++icEpoch;icChanged();
  if(!$('ambient').hidden)ambient(false);page('audio');roomAudioTab(true);
  try{await icPrepareMic(epoch);if(epoch!==icEpoch)return;const call=await icRequest('accept');if(epoch!==icEpoch){await icRequest('end',{},call.id);return;}icCall=call;await icStartMedia();}
  catch(error){icStopMedia();icError=error.message;}
  finally{icOperation=false;icOpening=false;icChanged();}
}
$('intercom-enable').onclick=async()=>{icEnabled=!icEnabled;icCall=null;icError=null;icRevision++;if(!icEnabled)icStopMedia();icChanged();await icPoll();};
$('intercom-answer').onclick=$('intercom-banner-answer').onclick=icAnswer;
$('intercom-end').onclick=$('intercom-banner-decline').onclick=icEnd;
intercomPanel.addEventListener('click',event=>{const button=event.target.closest('[data-call-room]');if(button&&!button.disabled)void icCallRoom(button.dataset.callRoom);});
$('intercom-mute').onclick=async()=>{
  if(icOperation||icCall?.status!=='active')return;icOperation=true;const epoch=icEpoch;
  try{
    if(icMic){icUploadGeneration++;icNode?.port.postMessage({type:'capture',enabled:false});icMic.getTracks().forEach(t=>t.stop());icMic=null;icSource?.disconnect();icSource=null;icQueue=[];await icRequest('mute',{muted:true});}
    else{await icPrepareMic(epoch);if(epoch!==icEpoch)return;await icRequest('mute',{muted:false});if(epoch!==icEpoch)return;icSource=icContext.createMediaStreamSource(icMic);icSource.connect(icNode);icNode.port.postMessage({type:'capture',enabled:true});}
  }catch{await icEnd();}finally{icOperation=false;icChanged();}
};
$('intercom-volume').oninput=()=>{$('intercom-volume-label').textContent=$('intercom-volume').value+'%';if(icGain)icGain.gain.value=Number($('intercom-volume').value)/100;};
player.addEventListener('play',()=>{if(intercomIsBusy())void icEnd();});
document.addEventListener('visibilitychange',()=>{if(document.hidden&&intercomIsBusy())void icEnd();});
window.addEventListener('pagehide',()=>{icEnabled=false;void icEnd();});
setInterval(icPoll,1000);

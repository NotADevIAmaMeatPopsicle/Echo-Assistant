'use strict';
endpoints.displayVoice='/v1/display/voice';
let micStream=null,micContext=null,micNode=null,micChunks=[],micSamples=0,micOpening=false,voiceRequest=null,voiceReplyUrl=null,voiceRequestHome=false,voiceEpoch=0,voiceCancelling=false,microphoneState=null;
const voicePlayer=$('voice-reply');voicePlayer.volume=.02;
function voiceButtons(){
  const inCall=typeof intercomIsBusy==='function'&&intercomIsBusy();
  displayCaptureBusy=micOpening || voiceCancelling || !!micStream || !!voiceRequest || !voicePlayer.paused || inCall;
  document.dispatchEvent(new Event('echo:audio-focus'));
  $('voice-start').dataset.unavailable=String(!data.displayVoice?.available || microphoneState==='none' || micOpening || voiceCancelling || !!micStream || !!voiceRequest || !!chatAbort || inCall);
  $('voice-send').hidden=!micStream;$('voice-cancel').hidden=!micOpening && !micStream && !voiceRequest && voicePlayer.paused;
  $('voice-start').hidden=!!micStream || !!voiceRequest;
  $('voice-wave').hidden=!micStream;$('chat-text').disabled=displayCaptureBusy;guardButtons();renderDisplayPresence();
}
function renderDisplayPresence(){
  const inCall=typeof intercomIsBusy==='function'&&intercomIsBusy();
  let active=inCall ? 'intercom' : micStream ? 'listening' : micOpening ? 'opening' : voiceCancelling ? 'stopping' : voiceRequest || chatAbort ? 'thinking' : !voicePlayer.paused ? 'speaking' : 'ready';
  const states={ready:['Ready when you are.','Type a thought, or tap to talk.'],opening:['A moment…','Opening this device’s microphone.'],listening:['I’m listening.','Speak naturally, then send your recording.'],thinking:['On it.','A little thinking. I’ll be right with you.'],speaking:['Here’s what I found.','Replying on this device.'],stopping:['Stopping…','Closing the microphone and request.'],intercom:['Room call','Use Room audio to answer, mute or hang up.'],disconnected:['Reconnecting to Echo…','Checking this display’s connection to the server.']};
  let detail=states[active];
  if(active==='ready'){
    if(!fresh('timers')||signInRequired){active='disconnected';detail=states.disconnected;}
    else if(data.health?.display_demo)detail=['Ready when you are.','Try the preview. Microphone and sound are off.'];
    else if(microphoneState==='none')detail=['Ready when you are.','Type to Echo. Connect a microphone to talk here.'];
    else if(!fresh('displayVoice')||!data.displayVoice?.available)detail=['Ready for a conversation.','Type to Echo. Speech service is unavailable.'];
  }
  const ringState=active==='intercom'?'thinking':active;
  $('assistant-orb').dataset.state=ringState;$('assistant-phase').textContent=detail[0];$('assistant-detail').textContent=detail[1];
  document.querySelectorAll('[data-orb]').forEach(orb=>orb.dataset.state=ringState);
  $('voice-caption').textContent=detail[0];$('voice-detail').textContent=detail[1];
  $('wake-word-status').textContent=data.health?.display_demo ? 'Voice preview · microphone off' : microphoneState==='none' ? 'Connect a microphone to this device. Local wake words are not enabled yet.' : 'Tap to talk with this device’s microphone. Local wake words are not enabled yet.';
}
async function detectMicrophone(){
  if(!navigator.mediaDevices?.enumerateDevices)return;
  try{const devices=await navigator.mediaDevices.enumerateDevices();microphoneState=devices.some(d=>d.kind==='audioinput') ? 'present' : 'none';voiceButtons();}catch{microphoneState=null;}
}
extensions.push(()=>{
  if(!micStream && !voiceRequest && !micOpening && !chatAbort && voicePlayer.paused){
    if(!data.displayVoice?.available)$('display-voice-status').textContent=data.health?.display_demo ? 'Preview only · voice capture is off.' : 'Voice service unavailable. You can still type.';
    else if(microphoneState==='none')$('display-voice-status').textContent='No microphone detected. You can still type.';
    else if($('display-voice-status').textContent==='Checking the speech service…')$('display-voice-status').textContent='Tap the microphone, or type a message.';
  }
  voiceButtons();
});
document.addEventListener('echo:conversation',voiceButtons);
document.addEventListener('echo:intercom',voiceButtons);
document.addEventListener('echo:voice-state',renderDisplayPresence);
navigator.mediaDevices?.addEventListener?.('devicechange',detectMicrophone);detectMicrophone();
function clearVoiceReply(){voicePlayer.pause();voicePlayer.hidden=true;voicePlayer.removeAttribute('src');voicePlayer.load();if(voiceReplyUrl)URL.revokeObjectURL(voiceReplyUrl);voiceReplyUrl=null;}
async function closeMic(){
  micStream?.getTracks().forEach(track=>track.stop());micStream=null;
  if(micNode){micNode.port.onmessage=null;micNode.disconnect();micNode=null;}
  const context=micContext;micContext=null;if(context && context.state!=='closed')await context.close();
}
function recordingWav(){
  const buffer=new ArrayBuffer(44+micSamples*2),view=new DataView(buffer);let offset=44;
  const text=(at,value)=>{for(let i=0;i<value.length;i++)view.setUint8(at+i,value.charCodeAt(i));};
  text(0,'RIFF');view.setUint32(4,36+micSamples*2,true);text(8,'WAVEfmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,16000,true);view.setUint32(28,32000,true);view.setUint16(32,2,true);view.setUint16(34,16,true);text(36,'data');view.setUint32(40,micSamples*2,true);
  for(const chunk of micChunks)for(const sample of chunk){view.setInt16(offset,sample,true);offset+=2;}
  return new Blob([buffer],{type:'audio/wav'});
}
async function finishVoice(){
  if(!micStream || voiceRequest)return;
  const recording=recordingWav(),epoch=voiceEpoch,samples=micSamples;micChunks=[];await closeMic();
  if(epoch!==voiceEpoch)return;
  if(samples<1600){$('display-voice-status').textContent='That recording was too short. Try again.';voiceButtons();return;}
  const controller=new AbortController();voiceRequest=controller;voiceButtons();$('display-voice-status').textContent='Thinking about that…';
  const spoken=appendChatMessage('user','Voice message · transcribing…',true),answer=appendChatMessage('assistant','Listening back to your message…',true);controller.answer=answer;controller.spoken=spoken;
  try{
    const timeout=setTimeout(()=>{if(voiceRequest===controller)cancelVoice();},120000);
    let response;
    try{response=await fetch('/v1/display/voice?allow_home='+voiceRequestHome+'&reply_audio='+$('voice-speak').checked,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'audio/wav','X-Echo-Request':'1'},body:recording,signal:controller.signal});}finally{clearTimeout(timeout);}
    const result=await response.json();if(!response.ok)throw new Error(result.detail || 'Echo could not finish this recording.');
    if(epoch!==voiceEpoch)return;
    finishChatMessage(spoken,{text:result.transcript || 'Voice message'});finishChatMessage(answer,result);
    $('display-voice-status').textContent=result.audio_error || (result.status==='complete' ? 'Reply ready.' : result.text);
    if(result.audio?.format==='wav'){
      const bytes=Uint8Array.from(atob(result.audio.data),c=>c.charCodeAt(0));voiceReplyUrl=URL.createObjectURL(new Blob([bytes],{type:'audio/wav'}));voicePlayer.src=voiceReplyUrl;voicePlayer.hidden=false;answer.append(voicePlayer);$('chat-reply').scrollTop=$('chat-reply').scrollHeight;
      try{await voicePlayer.play();if(epoch===voiceEpoch)$('display-voice-status').textContent='Speaking on this display.';}catch{if(epoch===voiceEpoch)$('display-voice-status').textContent='Reply ready. Press Play to listen.';}
    }
  }catch(error){if(epoch===voiceEpoch){const text=error.name==='AbortError' ? 'Request stopped. Check activity before retrying a home action.' : error.message;$('display-voice-status').textContent=text;finishChatMessage(spoken,{text:'Voice message'});finishChatMessage(answer,{text});}}
  finally{if(voiceRequest===controller)voiceRequest=null;voiceButtons();}
}
$('voice-start').onclick=async()=>{
  if(!data.displayVoice?.available || voiceRequest || micStream || micOpening || voiceCancelling || chatAbort)return;
  const epoch=++voiceEpoch;
  clearVoiceReply();player.pause();micOpening=true;voiceButtons();$('display-voice-status').textContent='Opening the microphone…';
  voiceRequestHome=$('allow-home').checked;$('allow-home').checked=false;
  try{
    if(!navigator.mediaDevices?.getUserMedia)throw new Error('Microphone access needs HTTPS or the Pi loopback bridge.');
    const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
    if(!micOpening || epoch!==voiceEpoch){stream.getTracks().forEach(track=>track.stop());return;}
    micStream=stream;micChunks=[];micSamples=0;micContext=new AudioContext({sampleRate:16000});
    await micContext.audioWorklet.addModule('/assets/display/capture-worklet.js');
    if(!micOpening || !micContext || epoch!==voiceEpoch)return;
    micNode=new AudioWorkletNode(micContext,'echo-capture');const source=micContext.createMediaStreamSource(stream),silence=micContext.createGain();silence.gain.value=0;
    micNode.port.onmessage=event=>{
      if(event.data.type==='pcm'){const chunk=new Int16Array(event.data.data);micChunks.push(chunk);micSamples+=chunk.length;$('display-voice-status').textContent='Listening · '+Math.max(0,Math.ceil(8-micSamples/16000))+' seconds left';}
      if(event.data.type==='done')finishVoice();
    };
    source.connect(micNode);micNode.connect(silence);silence.connect(micContext.destination);await micContext.resume();
    $('display-voice-status').textContent='Listening. Speak now.';
  }catch(error){if(epoch===voiceEpoch){await closeMic();$('display-voice-status').textContent=error.name==='NotAllowedError' ? 'Microphone permission was declined. You can still type to Echo.' : error.name==='NotFoundError' ? 'No microphone was found on this device.' : error.message;}}
  finally{if(epoch===voiceEpoch)micOpening=false;voiceButtons();}
};
$('voice-send').onclick=finishVoice;
async function cancelVoice(){
  if(voiceCancelling)return;voiceCancelling=true;voiceEpoch++;
  micOpening=false;await closeMic();micChunks=[];clearVoiceReply();
  const pending=voiceRequest;
  if(pending){try{const activity=await api('/v1/chat/activity');if(activity.active && activity.id)await api('/v1/chat/activity/'+activity.id+'/stop',{});$('display-voice-status').textContent='Stop requested. Check activity before retrying a home action.';}catch{$('display-voice-status').textContent='Could not confirm the host stopped. Check activity before retrying.';}finally{pending.abort();finishChatMessage(pending.spoken,{text:'Voice message · stopped'});finishChatMessage(pending.answer,{text:$('display-voice-status').textContent});}}
  else $('display-voice-status').textContent='Microphone closed.';
  voiceCancelling=false;voiceButtons();
}
$('voice-cancel').onclick=cancelVoice;
$('voice-volume').oninput=()=>{voicePlayer.volume=Number($('voice-volume').value)/100;$('voice-volume-label').textContent=$('voice-volume').value+'%';};
voicePlayer.onplay=voiceButtons;voicePlayer.onpause=voiceButtons;
voicePlayer.onended=()=>{$('display-voice-status').textContent='Ready when you are.';voiceButtons();};
document.addEventListener('echo:page',event=>{if(event.detail!=='assistant' && (micOpening || micStream || voiceRequest || !voicePlayer.paused))cancelVoice();});
document.addEventListener('visibilitychange',()=>{if(document.hidden && (micOpening || micStream))cancelVoice();});

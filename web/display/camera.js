/* Camera is explicit; only motion wake persists, and only after opting in. */
'use strict';
(()=>{
  const client=crypto.randomUUID().replaceAll('-','');
  const card=document.createElement('article');card.className='card deck-camera-card';card.id='deck-camera';
  card.innerHTML=`<div><span class="eyebrow">A NEW PERSPECTIVE</span><h2>Your camera</h2><p id="deck-camera-status" class="soft" role="status">Camera is off.</p></div>
    <div class="deck-camera-layout"><div><div class="deck-camera-view"><img id="deck-camera-image" alt="Live view from this Deck" hidden><video id="deck-camera-video" autoplay muted playsinline hidden></video><p id="deck-camera-empty">Open a preview when you’re ready.</p></div>
    <div class="row wrap"><button id="deck-camera-open" class="pill primary">Open preview</button><button id="deck-camera-close" class="pill">Close camera</button><button id="deck-camera-focus" class="pill" hidden>Focus once</button></div>
    <div id="deck-camera-orientation" class="row wrap" hidden><label class="check-label"><input id="deck-camera-mirror" type="checkbox">Mirror</label><label class="check-label"><input id="deck-camera-rotate" type="checkbox">Rotate 180°</label><label>Manual focus<input id="deck-camera-lens" type="range" min="0" max="4095" step="16" value="0"></label></div></div>
    <div><h3>Ask Echo about this view</h3><p id="deck-camera-provider" class="tiny soft">Checking image model…</p><form id="deck-camera-ask"><label>Your question<textarea id="deck-camera-question" maxlength="1200" rows="2" placeholder="What can you see?" required></textarea></label><button id="deck-camera-send" class="pill primary" disabled>Send this frame</button></form><p id="deck-camera-answer" class="camera-answer" role="status"></p>
    <h3>Video calls</h3><p class="tiny soft">In Room audio → Voice & video, start or join a call, then turn the camera on.</p><button id="deck-camera-calls" class="pill">Open calls</button>
    <form id="deck-camera-meet"><label>Google Meet code or link<input id="deck-camera-meet-code" placeholder="abc-defg-hij" maxlength="120" required></label><button class="pill" id="deck-camera-meet-open">Open Google Meet</button></form><button id="deck-camera-meet-close" class="pill" hidden>Close Meet and return</button><p class="tiny soft">Meet opens separately. Sign in there if needed, choose Echo Camera, then join. Closing that window releases the camera. Google Calendar sign-in does not sign you into Meet.</p></div></div>`;
  experiencePage.append(card);
  const settings=document.createElement('article');settings.className='card';settings.hidden=true;
  settings.innerHTML=`<span class="eyebrow">CAMERA COMFORT</span><h2>Wake when something moves</h2><p class="soft">Use this Deck’s camera to wake its screen. Motion is processed on the Pi. No pictures are sent or recorded.</p><label class="check-label"><input id="deck-camera-presence" type="checkbox">Enable camera motion wake</label><p class="tiny soft" id="deck-camera-presence-note">Off by default. This keeps the camera active. Preview and calling suspend motion wake until you enable it again.</p><button id="deck-camera-all-off" class="pill">Turn camera and motion wake off</button>`;
  $('page-settings').append(settings);
  const indicator=document.createElement('button');indicator.id='deck-camera-indicator';indicator.className='pill';indicator.hidden=true;indicator.textContent='● Camera on · turn off';document.body.append(indicator);
  let state={},vision={},lease=null,timer=null,stream=null,callStream=null,url=null,frame=null,epoch=0,preview=false,opening=false,questionBusy=false,pollBusy=false,lastMotion=null,askAbort=null,access=null;
  const version=()=>`${data.session?.receiver_id||'owner'}:${data.session?.profile_revision||0}:${data.session?.member?.id||''}`;
  const post=(suffix,body)=>api('/v1/display/camera/'+suffix,body);
  function report(text){$('deck-camera-status').textContent=text;}
  function clearView(){if(url)URL.revokeObjectURL(url);url=null;frame=null;$('deck-camera-image').removeAttribute('src');$('deck-camera-image').hidden=true;$('deck-camera-video').srcObject=null;$('deck-camera-video').hidden=true;$('deck-camera-empty').hidden=false;}
  async function close(){
    ++epoch;opening=false;preview=false;askAbort?.abort();clearInterval(timer);timer=null;
    const old=lease;lease=null;stream?.getTracks().forEach(t=>t.stop());stream=null;callStream?.getTracks().forEach(t=>t.stop());callStream=null;clearView();
    if(old)try{await post('stop',old);}catch{}report('Camera is off.');render();
  }
  function render(){
    const native=state.supported===true;
    settings.hidden=!native;$('deck-camera-orientation').hidden=!native;
    $('deck-camera-open').disabled=opening||preview||!!lease;
    $('deck-camera-close').disabled=!preview&&!lease;
    $('deck-camera-send').disabled=!preview||!vision.available||questionBusy||!frame&&!stream;
    $('deck-camera-focus').hidden=!native||!state.focus_supported;$('deck-camera-focus').disabled=!preview||state.focusing;
    $('deck-camera-lens').disabled=!preview||!state.focus_supported||state.focusing;
    $('deck-camera-meet-close').hidden=!state.meet_active;
    $('deck-camera-provider').textContent=vision.available?`Send one frame to ${vision.provider} · ${vision.model}. Echo does not save the image.`:'Select an image-capable model in Echo Settings before asking an image question.';
    indicator.hidden=!state.capturing&&!stream&&!callStream;
    indicator.textContent=state.purpose==='presence'?'● Motion camera on · turn off':'● Camera on · turn off';
    $('deck-camera-presence-note').textContent=state.presence_suspended&&state.settings?.presence?'Motion wake is suspended. Switch it off and on to resume.':'Off by default. This keeps the camera active. Preview and calling suspend motion wake until you enable it again.';
    if(state.settings){$('deck-camera-presence').checked=state.settings.presence;$('deck-camera-mirror').checked=state.settings.mirror;$('deck-camera-rotate').checked=state.settings.rotate===180;}
  }
  async function status(){
    if(pollBusy)return;pollBusy=true;
    try{state=await api('/v1/display/camera');if(state.motion_at>lastMotion){if(lastMotion!==null)document.dispatchEvent(new Event('echo:camera-motion'));}lastMotion=state.motion_at||0;
      if(state.error)report(state.error);else if(state.focusing)report('Finding focus…');
      if(state.focus!=null&&document.activeElement!==$('deck-camera-lens'))$('deck-camera-lens').value=state.focus;
      if(lease&&!state.purpose&&!opening)await close();render();
    }catch{if(lease||stream)await close();state={};render();}finally{pollBusy=false;}
  }
  async function acquire(purpose){
    await close();const mark=++epoch;opening=true;access=version();render();
    try{
      state=await api('/v1/display/camera');
      if(mark!==epoch)throw new Error('Camera opening cancelled');
      if(!state.supported){opening=false;return {native:false,mark,release:close};}
      const result=await post('start',{client,purpose});const next={client,lease:result.lease};
      if(mark!==epoch){await post('stop',next);throw new Error('Camera opening cancelled');}
      lease=next;timer=setInterval(()=>post('pulse',next).catch(()=>{if(lease===next)void close();}),3000);
      for(let i=0;i<30;i++){if(mark!==epoch)throw new Error('Camera opening cancelled');state=await api('/v1/display/camera');if(state.error)throw new Error(state.error);if(state.ready)break;await new Promise(r=>setTimeout(r,200));}
      if(!state.ready)throw new Error('Camera is not ready. Check its connection.');
      opening=false;render();return {native:true,mark,release:()=>{if(lease===next)return close();}};
    }catch(e){if(mark===epoch)await close();throw e;}
  }
  async function latestFrame(){
    if(stream){const video=$('deck-camera-video');if(!video.videoWidth)throw new Error('Camera is warming up');const canvas=document.createElement('canvas');canvas.width=640;canvas.height=Math.round(640*video.videoHeight/video.videoWidth);canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);return await new Promise(r=>canvas.toBlob(r,'image/jpeg',.8));}
    if(!lease)throw new Error('Open the camera first');
    const r=await fetch('/v1/display/camera/frame',{method:'POST',headers:{'Content-Type':'application/json','X-Echo-Request':'1','X-Echo-Profile-Revision':String(data.session?.profile_revision||0)},body:JSON.stringify(lease),signal:AbortSignal.timeout(4000),cache:'no-store'});
    if(!r.ok)throw new Error('Camera frame unavailable');return r.blob();
  }
  async function previewFrames(mark){
    while(preview&&mark===epoch){try{const blob=await latestFrame();if(mark!==epoch)return;frame=blob;const next=URL.createObjectURL(blob);$('deck-camera-image').src=next;$('deck-camera-image').hidden=false;$('deck-camera-empty').hidden=true;if(url)URL.revokeObjectURL(url);url=next;render();}catch{if(mark===epoch)report('Waiting for the camera…');}await new Promise(r=>setTimeout(r,250));}
  }
  $('deck-camera-open').onclick=async()=>{try{
    if(data.health?.display_demo)throw new Error('Hardware capture is disabled in this preview.');
    const handle=await acquire('preview');if(handle.mark!==epoch)return;
    if(!handle.native){const next=await navigator.mediaDevices.getUserMedia({video:{width:{ideal:640},height:{ideal:360}},audio:false});if(handle.mark!==epoch){next.getTracks().forEach(t=>t.stop());return;}stream=next;$('deck-camera-video').srcObject=stream;$('deck-camera-video').hidden=false;$('deck-camera-empty').hidden=true;}
    preview=true;report('Live preview · images stay on this device.');render();if(handle.native)void previewFrames(handle.mark);
  }catch(e){await close();report(e.message||'Camera permission or connection unavailable.');}};
  $('deck-camera-close').onclick=()=>void close();
  async function off(){document.dispatchEvent(new Event('echo:camera-off'));await close();if(state.supported)try{state=await post('off',{});}catch(e){report(e.message);}render();}
  indicator.onclick=$('deck-camera-all-off').onclick=()=>void off();
  for(const id of ['mirror','rotate','presence','lens'])$('deck-camera-'+id).onchange=async()=>{try{
    const next={...state.settings,mirror:$('deck-camera-mirror').checked,rotate:$('deck-camera-rotate').checked?180:0,presence:$('deck-camera-presence').checked};if(id==='lens')next.focus=Number($('deck-camera-lens').value);
    state=await api('/v1/display/camera',next,'PUT');render();
  }catch(e){toast(e.message);void status();}};
  $('deck-camera-focus').onclick=async()=>{try{await post('focus',lease);report('Finding focus…');}catch(e){report(e.message);}};
  $('deck-camera-ask').onsubmit=async e=>{e.preventDefault();if(!preview||questionBusy)return;questionBusy=true;const mark=epoch;askAbort=new AbortController();render();$('deck-camera-answer').textContent='Looking at this frame…';try{
    const blob=await latestFrame();const image=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=reject;reader.readAsDataURL(blob);});
    const result=await api('/v1/display/vision',{image,question:$('deck-camera-question').value},'POST',AbortSignal.any([askAbort.signal,AbortSignal.timeout(55000)]));if(mark===epoch)$('deck-camera-answer').textContent=result.text;
  }catch(e){if(mark===epoch)$('deck-camera-answer').textContent=e.message||'The selected model could not answer about this image.';}finally{questionBusy=false;askAbort=null;render();}};
  $('deck-camera-calls').onclick=()=>{page('audio');if(!$('page-audio').hidden)$('room-tab-calling').click();};
  $('deck-camera-meet').onsubmit=async e=>{e.preventDefault();const code=$('deck-camera-meet-code').value.trim().replace(/^https:\/\/meet.google.com\//,'').replace(/\/$/,'');if(!/^[a-z]{3}-[a-z]{4}-[a-z]{3}$/.test(code)){toast('Enter a Meet code such as abc-defg-hij.');return;}
    if(data.health?.display_demo){toast('Meet launch is disabled in this preview.');return;}
    if(!state.supported){window.open('https://meet.google.com/'+code,'_blank','noopener,noreferrer');return;}
    try{await close();await post('meet',{client,code});report('Meet is open. Close its window to return to Echo.');void status();}catch(e){report(e.message);}};
  $('deck-camera-meet-close').onclick=()=>void off();
  window.EchoCamera={async openCall(){
    // CSI uses the same bounded local feed as preview. Chromium need not open
    // raw camera nodes or keep a virtual webcam alive when video is off.
    const h=await acquire('preview');if(!h.native)return {options:{},release:h.release};
    try{
      const canvas=document.createElement('canvas');canvas.width=640;canvas.height=360;
      const context=canvas.getContext('2d');
      async function draw(){const bitmap=await createImageBitmap(await latestFrame());try{if(epoch===h.mark)context.drawImage(bitmap,0,0,640,360);}finally{bitmap.close();}}
      await draw();if(epoch!==h.mark)throw new Error('Camera opening cancelled');
      const output=canvas.captureStream(10);callStream=output;render();
      void (async()=>{let failures=0;while(epoch===h.mark&&callStream===output){
        try{await draw();failures=0;}catch{if(++failures>=3){document.dispatchEvent(new Event('echo:camera-off'));await h.release();break;}}
        await new Promise(resolve=>setTimeout(resolve,100));
      }})();
      return {track:output.getVideoTracks()[0],release:h.release};
    }catch(e){await h.release();throw e;}
  },get active(){return !!lease||!!stream||!!callStream;}};
  document.addEventListener('echo:page',e=>{if(e.detail!=='day'&&preview)void close();});
  document.addEventListener('visibilitychange',()=>{if(document.hidden&&(preview||opening))void close();});
  window.addEventListener('pagehide',()=>{void close();});
  extensions.push(()=>{if((preview||lease)&&(access!==version()||signInRequired))void close();});
  setInterval(()=>{if(!document.hidden)void status();},2000);
  void status();api('/v1/display/vision').then(v=>{vision=v;render();}).catch(()=>render());
})();

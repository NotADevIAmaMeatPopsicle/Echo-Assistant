'use strict';
const radioCard=document.createElement('article');radioCard.className='card';
radioCard.innerHTML='<div class="row spread wrap"><div><span class="eyebrow">TUNE IN</span><h2>Your radio stations.</h2></div><button id="radio-manage" class="pill">Manage stations</button></div><p class="soft">Saved streams play through this display’s audio output.</p><label>Radio station<select id="radio-choice"><option value="">Choose a saved station</option></select></label><p id="radio-origin" class="tiny soft"></p><button id="radio-play" class="pill primary" data-requires="media">Play station</button><p id="radio-empty" class="soft">No stations yet. Add a direct HTTPS audio stream in Settings.</p>';
$('local-panel').append(radioCard);
const filesCard=document.createElement('article');filesCard.className='card';
filesCard.innerHTML='<div class="row spread wrap"><div><span class="eyebrow">FROM THIS DEVICE</span><h2>Your listening queue.</h2></div><button id="media-clear" class="text-button" disabled>Clear queue</button></div><p class="soft">Choose music or video files from this device. Files stay here and are never uploaded.</p><label class="file-button pill primary" for="local-media-file">Add files</label><input id="local-media-file" class="sr-only" type="file" multiple accept="audio/*,video/mp4,video/webm,.mp3,.m4a,.aac,.ogg,.oga,.opus,.wav,.flac,.mp4,.webm"><p class="tiny soft">Up to 32 files, 500 MB each. Browser codec support varies. The queue clears when you reload.</p><ol id="media-queue" class="media-queue"></ol>';
$('files-panel').append(filesCard);
const mediaCard=document.createElement('article');mediaCard.className='card local-media-player';mediaCard.hidden=true;
mediaCard.innerHTML='<span class="eyebrow">PLAYING ON THIS DISPLAY</span><h3 id="display-media-title">Nothing queued yet.</h3><p id="display-media-status" class="soft" role="status">Choose a station or add local files.</p><video id="display-media" playsinline preload="metadata" hidden></video><div id="media-timeline" hidden><label class="sr-only" for="media-seek">Playback position</label><input id="media-seek" type="range" min="0" max="1" value="0" step="1"><div class="row spread tiny soft"><span id="media-elapsed">0:00</span><span id="media-duration">0:00</span></div></div><div class="row wrap media-transport"><button id="media-previous" class="pill" disabled>Previous</button><button id="media-toggle" class="pill primary" disabled>Play</button><button id="media-next" class="pill" disabled>Next</button><button id="display-media-stop" class="pill" disabled>Stop</button></div><label class="media-volume">Radio & file volume <output id="display-volume-label">2%</output><input id="display-volume" type="range" min="0" max="100" value="2"></label><p class="tiny soft">Uses this browser’s speaker. Does not change Spotify or a room speaker.</p>';
$('page-music').append(mediaCard);
const radioOwner=document.createElement('article');radioOwner.className='card pairing-card';radioOwner.id='radio-settings';radioOwner.hidden=true;
radioOwner.innerHTML='<span class="eyebrow">YOUR OWN STATIONS</span><h2>Radio presets</h2><p class="soft">Add a direct HTTPS audio stream, such as an MP3 or AAC station stream. A station’s website or a paid streaming page is not a direct stream.</p><div id="radio-presets"></div><form id="radio-add"><label>Station name<input id="radio-name" maxlength="80" required></label><label>HTTPS stream URL<input id="radio-url" type="url" maxlength="2048" placeholder="https://stream.example/radio.mp3" required></label><button class="pill primary" type="submit" data-requires="media">Add station</button></form>';
$('page-settings').append(radioOwner);endpoints.media='/v1/display/media';
const player=$('display-media');player.volume=.02;
let mediaQueue=[],queueIndex=-1,mediaSource=null,localMediaUrl=null,mediaGeneration=0,mediaStarting=false,mediaSeeking=false,stationSignature='',mediaIdentity='';
function mediaStatus(text){$('display-media-status').textContent=text;}
function releaseMediaFocus(){document.dispatchEvent(new Event('echo:audio-focus'));}
function stopDisplayMedia(){
  mediaGeneration++;mediaStarting=false;player.pause();player.hidden=true;player.removeAttribute('src');player.load();
  if(localMediaUrl)URL.revokeObjectURL(localMediaUrl);localMediaUrl=null;releaseMediaFocus();renderMediaTransport();
}
function renderMediaTransport(){
  const preview=!!data.health?.display_demo,has=!!mediaSource;
  $('media-toggle').disabled=!has||preview||mediaStarting;$('media-toggle').textContent=mediaStarting?'Connecting…':!player.paused?'Pause':player.error?'Retry':'Play';
  $('display-media-stop').disabled=!player.getAttribute('src')&&!mediaStarting;
  $('media-previous').disabled=mediaSource?.kind!=='file'||queueIndex<=0||mediaStarting;
  $('media-next').disabled=mediaSource?.kind!=='file'||queueIndex>=mediaQueue.length-1||mediaStarting;
  $('media-clear').disabled=!mediaQueue.length;
  const duration=Number.isFinite(player.duration)?player.duration:0;$('media-timeline').hidden=mediaSource?.kind!=='file'||!duration;
  if(!mediaSeeking){$('media-seek').max=duration||1;$('media-seek').value=player.currentTime||0;}
  $('media-elapsed').textContent=musicTime((player.currentTime||0)*1000);$('media-duration').textContent=musicTime(duration*1000);
}
function renderMediaQueue(){
  $('media-queue').innerHTML=mediaQueue.map((f,i)=>`<li class="${mediaSource?.kind==='file'&&queueIndex===i?'selected':''}"><button class="media-file-select" data-media-file="${i}" ${queueIndex===i&&mediaSource?.kind==='file'?'aria-current="true"':''}><span>${i+1}</span><strong>${esc(f.name)}</strong><small>${(f.size/1048576).toFixed(1)} MB</small></button><button class="text-button" data-media-remove="${i}" aria-label="Remove ${esc(f.name)}">×</button></li>`).join('')||'<li class="soft">Your queue is empty. Add files to get started.</li>';
  renderMediaTransport();
}
function loadMedia(source){
  stopDisplayMedia();mediaSource=source;
  if(source.kind==='file'){const file=mediaQueue[source.index];queueIndex=source.index;if(file instanceof File){localMediaUrl=URL.createObjectURL(file);player.src=localMediaUrl;}else{player.src=file.url;}player.hidden=!(file.type.startsWith('video/')||/\.(mp4|webm)$/i.test(file.name));}
  else{player.src=source.url;player.hidden=true;}
  $('display-media-title').textContent=source.name;mediaStatus('Ready. Press Play to start.');renderMediaQueue();
}
async function playDisplayMedia(){
  if(!mediaSource||mediaStarting||data.health?.display_demo)return;
  if(!player.getAttribute('src')||player.error)loadMedia(mediaSource);
  const generation=mediaGeneration;mediaStarting=true;mediaStatus('Connecting…');renderMediaTransport();
  try{
    if(typeof prepareLocalAudio==='function')await prepareLocalAudio();
    if(generation!==mediaGeneration){releaseMediaFocus();return;}
    await player.play();
    if(generation===mediaGeneration)mediaStatus('Playing on this display.');
  }catch(error){if(generation===mediaGeneration){player.pause();mediaStatus(error.name==='NotAllowedError'?'Tap Play again to allow audio in this browser.':'Could not play. Check the connection or file format, then press Retry.');}releaseMediaFocus();}
  finally{if(generation===mediaGeneration){mediaStarting=false;releaseMediaFocus();renderMediaTransport();}}
}
document.addEventListener('echo:music-tab',event=>{mediaCard.hidden=!['local','files'].includes(event.detail);});
extensions.push(()=>{
  const identity=signInRequired?'':JSON.stringify([data.session?.role,data.session?.receiver_id,data.session?.profile_revision,data.session?.member]);
  if(mediaIdentity&&mediaIdentity!==identity){stopDisplayMedia();mediaQueue=[];queueIndex=-1;mediaSource=null;$('display-media-title').textContent='Nothing queued yet.';mediaStatus('Session changed. Choose media for this session.');renderMediaQueue();}
  mediaIdentity=identity;
  const owner=data.session?.role==='owner';radioOwner.hidden=!owner;$('radio-manage').hidden=!owner;
  const stations=data.media?.stations||[],signature=JSON.stringify(stations);
  if(signature!==stationSignature){stationSignature=signature;const selected=$('radio-choice').value;
    $('radio-choice').innerHTML='<option value="">Choose a saved station</option>'+stations.map(s=>`<option value="${esc(s.url)}">${esc(s.name)}</option>`).join('');$('radio-choice').value=selected;
    $('radio-presets').innerHTML=stations.map((s,i)=>`<div class="schedule-item row spread"><span>${esc(s.name)}</span><button class="pill" data-remove-radio="${i}">Remove</button></div>`).join('')||empty('No saved stations.');
  }
  $('radio-empty').hidden=!!stations.length;$('radio-empty').textContent=!fresh('media')?'Station list unavailable. Check the connection to your Echo host.':owner?'No stations yet. Add a direct HTTPS audio stream in Settings.':'No stations yet. Ask the owner to add streams in Settings.';
  $('radio-play').dataset.unavailable=String(!$('radio-choice').value||!!data.health?.display_demo);$('local-media-file').disabled=!!data.health?.display_demo;
  if(data.health?.display_demo)mediaStatus('Silent preview. Playback is available on a live display.');renderMediaTransport();
});
$('radio-manage').onclick=()=>{if(window.EchoSettings.open('music',radioOwner))$('radio-name').focus({preventScroll:true});};
$('radio-choice').onchange=()=>{const value=$('radio-choice').value;$('radio-origin').textContent=value?`Play contacts ${new URL(value).hostname} from this display.`:'';$('radio-play').dataset.unavailable=String(!value||!!data.health?.display_demo);guardButtons();};
$('radio-play').onclick=()=>{if(!fresh('media')||data.health?.display_demo)return;const station=data.media.stations.find(s=>s.url===$('radio-choice').value);if(station){loadMedia({kind:'radio',...station});void playDisplayMedia();}};
$('local-media-file').onchange=event=>{
  const files=[...event.target.files];event.target.value='';if(data.health?.display_demo)return;
  const types={mp3:'audio/mpeg',m4a:'audio/mp4',aac:'audio/aac',ogg:'audio/ogg',oga:'audio/ogg',opus:'audio/ogg; codecs=opus',wav:'audio/wav',flac:'audio/flac',mp4:'video/mp4',webm:'video/webm'};
  let skipped=0;for(const f of files){const type=f.type&&f.type!=='application/octet-stream'?f.type:types[f.name.split('.').pop().toLowerCase()];if(mediaQueue.length>=32||!f.size||f.size>500000000||!type||!player.canPlayType(type)){skipped++;continue;}mediaQueue.push(f);}
  if(!mediaSource&&mediaQueue.length)loadMedia({kind:'file',index:0,name:mediaQueue[0].name});else renderMediaQueue();
  if(skipped)toast(`${skipped} file(s) skipped: unsupported format, empty, over 500 MB, or queue full.`);
};
$('media-queue').onclick=event=>{
  const select=event.target.closest('[data-media-file]'),remove=event.target.closest('[data-media-remove]');
  if(select){const index=Number(select.dataset.mediaFile);loadMedia({kind:'file',index,name:mediaQueue[index].name});}
  if(remove){const index=Number(remove.dataset.mediaRemove);if(mediaSource?.kind==='file'&&index===queueIndex){stopDisplayMedia();mediaSource=null;queueIndex=-1;$('display-media-title').textContent='Choose another file.';mediaStatus('Removed from queue.');}else if(mediaSource?.kind==='file'&&index<queueIndex){queueIndex--;mediaSource.index=queueIndex;}mediaQueue.splice(index,1);renderMediaQueue();}
};
$('media-clear').onclick=()=>{if(mediaSource?.kind==='file'){stopDisplayMedia();mediaSource=null;$('display-media-title').textContent='Nothing queued yet.';mediaStatus('Queue cleared.');}mediaQueue=[];queueIndex=-1;renderMediaQueue();};
for(const [id,delta] of [['media-previous',-1],['media-next',1]])$(id).onclick=()=>{const index=queueIndex+delta;if(index<0||index>=mediaQueue.length)return;const playing=!player.paused;loadMedia({kind:'file',index,name:mediaQueue[index].name});if(playing)void playDisplayMedia();};
$('media-toggle').onclick=()=>{if(!player.paused){player.pause();mediaStatus('Paused.');}else void playDisplayMedia();};
$('display-media-stop').onclick=()=>{stopDisplayMedia();mediaStatus('Stopped. Press Play to restart.');};
$('display-volume').oninput=()=>{player.volume=Number($('display-volume').value)/100;$('display-volume-label').textContent=$('display-volume').value+'%';};
$('media-seek').oninput=()=>{mediaSeeking=true;$('media-elapsed').textContent=musicTime(Number($('media-seek').value)*1000);};
$('media-seek').onchange=()=>{if(Number.isFinite(player.duration))player.currentTime=Number($('media-seek').value);mediaSeeking=false;};
$('media-seek').onblur=$('media-seek').onpointercancel=()=>{mediaSeeking=false;};
for(const event of ['play','pause','loadedmetadata','timeupdate'])player.addEventListener(event,renderMediaTransport);
player.addEventListener('pause',releaseMediaFocus);
player.addEventListener('waiting',()=>{if(player.getAttribute('src'))mediaStatus('Buffering…');});
player.addEventListener('playing',()=>mediaStatus('Playing on this display.'));
player.addEventListener('error',()=>{if(player.getAttribute('src')){mediaStatus('Playback unavailable. Check the stream or codec, then press Retry.');player.pause();releaseMediaFocus();renderMediaTransport();}});
player.addEventListener('ended',()=>{if(mediaSource?.kind==='file'&&queueIndex+1<mediaQueue.length){const index=queueIndex+1;loadMedia({kind:'file',index,name:mediaQueue[index].name});void playDisplayMedia();}else{mediaStatus('Finished.');releaseMediaFocus();renderMediaTransport();}});
window.addEventListener('pagehide',stopDisplayMedia);
$('radio-add').onsubmit=event=>{event.preventDefault();if(!fresh('media'))return;void action(async()=>{await api('/v1/display/media',{revision:data.media.revision,stations:[...data.media.stations,{name:$('radio-name').value,url:$('radio-url').value}]},'PUT');$('radio-add').reset();},'Radio preset saved.');};
radioOwner.addEventListener('click',event=>{const button=event.target.closest('[data-remove-radio]');if(button&&fresh('media'))void action(()=>api('/v1/display/media',{revision:data.media.revision,stations:data.media.stations.filter((_,i)=>i!==Number(button.dataset.removeRadio))},'PUT'),'Station removed.');});
renderMediaQueue();

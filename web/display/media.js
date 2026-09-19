'use strict';
const mediaCard=document.createElement('article');mediaCard.className='card pairing-card';
mediaCard.innerHTML='<span class="eyebrow">ON THIS DISPLAY</span><h2>Radio & local media</h2><p class="soft">Play through this screen’s audio output. Spotify and room speakers use the controls above.</p><label>Radio station<select id="radio-choice"><option value="">Choose a saved station</option></select></label><p id="radio-origin" class="tiny soft">Pressing Play contacts the selected streaming provider from this display.</p><div class="row wrap"><button id="radio-play" class="pill primary" type="button" data-requires="media">Play station</button><label class="file-button pill">Choose a local file<input id="local-media-file" type="file" accept="audio/mpeg,audio/mp4,audio/ogg,audio/wav,video/mp4,video/webm" hidden></label><button id="display-media-stop" class="pill" type="button">Stop</button></div><label class="media-volume">Display volume <span id="display-volume-label">2%</span><input id="display-volume" type="range" min="0" max="100" value="2"></label><video id="display-media" controls playsinline preload="none" hidden></video><p id="display-media-status" class="tiny soft">Ready. Local files stay on this device; codec support depends on its browser.</p>';
$('local-panel').append(mediaCard);
const radioOwner=document.createElement('article');radioOwner.className='card pairing-card';radioOwner.hidden=true;
radioOwner.innerHTML='<span class="eyebrow">YOUR OWN STATIONS</span><h2>Radio presets</h2><p class="soft">Add a direct HTTPS audio stream, such as an MP3 or AAC station stream. A station’s website or a paid streaming page is not a direct stream.</p><div id="radio-presets"></div><form id="radio-add"><label>Station name<input id="radio-name" maxlength="80" required></label><label>HTTPS stream URL<input id="radio-url" type="url" maxlength="2048" placeholder="https://stream.example/radio.mp3" required></label><button class="pill primary" type="submit" data-requires="media">Add station</button></form>';
$('page-settings').append(radioOwner);endpoints.media='/v1/display/media';
let localMediaUrl=null,stationSignature='';
const player=$('display-media');player.volume=.02;
function stopDisplayMedia(){player.pause();player.hidden=true;player.removeAttribute('src');player.load();if(localMediaUrl)URL.revokeObjectURL(localMediaUrl);localMediaUrl=null;}
extensions.push(()=>{
  radioOwner.hidden=data.session?.role!=='owner';
  const stations=data.media?.stations || [],signature=JSON.stringify(stations);
  if(signature!==stationSignature){stationSignature=signature;
    const selected=$('radio-choice').value;
    $('radio-choice').innerHTML='<option value="">Choose a saved station</option>'+stations.map((s,index)=>`<option value="${index}">${esc(s.name)}</option>`).join('');
    $('radio-choice').value=selected;
    $('radio-presets').innerHTML=stations.map((s,index)=>`<div class="schedule-item row spread"><span>${esc(s.name)}<small class="soft"> · ${esc(new URL(s.url).hostname)}</small></span><button class="pill" type="button" data-remove-radio="${index}">Remove</button></div>`).join('') || empty('No saved stations.');
  }
  $('radio-play').dataset.unavailable=String($('radio-choice').value==='' || !!data.health?.display_demo);
  $('local-media-file').disabled=!!data.health?.display_demo;
  if(data.health?.display_demo)$('display-media-status').textContent='Silent preview. Audio and video playback are available on a live display.';
});
$('radio-choice').onchange=()=>{const station=data.media?.stations[Number($('radio-choice').value)];$('radio-origin').textContent=$('radio-choice').value!=='' && station ? `Play contacts ${new URL(station.url).hostname} directly from this display.` : 'Choose a saved station.';$('radio-play').dataset.unavailable=String($('radio-choice').value==='' || !!data.health?.display_demo);guardButtons();};
$('radio-play').onclick=async()=>{
  if(!fresh('media') || $('radio-choice').value==='' || data.health?.display_demo)return;
  const station=data.media.stations[Number($('radio-choice').value)];if(!station)return;
  stopDisplayMedia();player.src=station.url;player.hidden=false;
  try{await player.play();$('display-media-status').textContent='Playing '+station.name+' on this display.';}catch{$('display-media-status').textContent='Could not start the stream. Check its URL, browser format support, and connection.';}
};
$('local-media-file').onchange=event=>{
  const file=event.target.files[0];event.target.value='';if(!file)return;
  if(file.size>500000000 || !player.canPlayType(file.type))return toast('Choose a supported audio or video file under 500 MB.');
  stopDisplayMedia();localMediaUrl=URL.createObjectURL(file);player.src=localMediaUrl;player.hidden=false;
  $('display-media-status').textContent=file.name+' · ready; press Play in the player.';
};
$('display-media-stop').onclick=()=>{stopDisplayMedia();$('display-media-status').textContent='Stopped.';};
$('display-volume').oninput=()=>{player.volume=Number($('display-volume').value)/100;$('display-volume-label').textContent=$('display-volume').value+'%';};
player.addEventListener('error',()=>{if(player.getAttribute('src'))$('display-media-status').textContent='Playback unavailable. This browser may not support the stream or codec.';});
$('radio-add').onsubmit=event=>{event.preventDefault();if(!fresh('media'))return;action(async()=>{
  await api('/v1/display/media',{revision:data.media.revision,stations:[...data.media.stations,{name:$('radio-name').value,url:$('radio-url').value}]},'PUT');$('radio-add').reset();
},'Radio preset saved.');};
radioOwner.addEventListener('click',event=>{const button=event.target.closest('[data-remove-radio]');if(button && fresh('media'))action(()=>api('/v1/display/media',{revision:data.media.revision,stations:data.media.stations.filter((_,i)=>i!==Number(button.dataset.removeRadio))},'PUT'),'Station removed.');});

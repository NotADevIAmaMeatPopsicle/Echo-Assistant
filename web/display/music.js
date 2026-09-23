/* Current playback only: no browsing history or track metadata in browser storage. */
'use strict';
let musicReceiver='display';
function musicSnapshotPath(){return musicReceiver==='round'?'/v1/music/now-playing':'/v1/display/music/now-playing';}
$('music-receiver').onchange=()=>{musicReceiver=$('music-receiver').value;delete data.nowPlaying;delete received.nowPlaying;renderMusicPanel();refresh();};
const musicDrags=new Set();let coverSource='',speakerMusicSignature='';
function sharedMusicOutput(){
  if(!fresh('groupMusic'))return null;
  const items=data.groupMusic?.items||[];
  if(musicReceiver.startsWith('group:'))return items.find(p=>p.id===musicReceiver.slice(6));
  if(musicReceiver!=='display'||['playing','paused'].includes(data.nowPlaying?.status))return null;
  const local=items.filter(p=>p.name===data.piAudio?.settings?.name);
  return local.length===1&&(['playing','paused'].includes(local[0].state)||(local[0].queue_playback&&local[0].title))?local[0]:null;
}
function sharedMusicState(p){return {available:p.available&&!p.blocked,receiver_name:p.name,status:p.state,title:p.title,artist:p.artist,album:p.album||'Spotify · Music Assistant',artwork:p.artwork,volume:p.volume,output_configured:true,capabilities:p.features.includes('volume_set')?['volume']:[],duration_ms:p.duration_ms||0,position_ms:p.position_ms||0};}
function chooseSharedMusic(id){musicReceiver='group:'+id;updateMusicChoices();$('music-receiver').value=musicReceiver;renderMusicPanel();}
function updateMusicChoices(){
  const select=$('music-receiver'),value=musicReceiver;
  const items=(data.groupMusic?.items||[]).filter(p=>p.available&&!p.blocked);
  const signature=JSON.stringify(items.map(p=>[p.id,p.name]));if(select.dataset.groups!==signature){select.querySelectorAll('option[data-shared]').forEach(o=>o.remove());for(const p of items){const o=new Option(p.name+' · Music library','group:'+p.id);o.dataset.shared='1';select.add(o);}select.dataset.groups=signature;select.value=value;}
}
function musicTime(ms){const seconds=Math.max(0,Math.floor(ms/1000));return `${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;}
function selectMusicTab(name,focus=false){
  document.querySelectorAll('[data-music-tab]').forEach(button=>{const selected=button.dataset.musicTab===name;button.classList.toggle('selected',selected);button.setAttribute('aria-selected',String(selected));button.tabIndex=selected?0:-1;$(button.getAttribute('aria-controls')).hidden=!selected;if(selected&&focus)button.focus();});
  document.querySelector('main').scrollTop=0;
  document.dispatchEvent(new CustomEvent('echo:music-tab',{detail:name}));
}
document.querySelectorAll('[data-music-tab]').forEach(button=>{
  button.onclick=()=>selectMusicTab(button.dataset.musicTab);
  button.onkeydown=event=>{const names=[...document.querySelectorAll('[data-music-tab]')].filter(b=>!b.hidden).map(b=>b.dataset.musicTab),index=names.indexOf(button.dataset.musicTab);let next;
    if(event.key==='ArrowRight')next=(index+1)%names.length;if(event.key==='ArrowLeft')next=(index+names.length-1)%names.length;if(event.key==='Home')next=0;if(event.key==='End')next=names.length-1;
    if(next!==undefined){event.preventDefault();selectMusicTab(names[next],true);}
  };
});
function renderMusicPanel(){
  updateMusicChoices();const group=sharedMusicOutput(),state=group?sharedMusicState(group):!musicReceiver.startsWith('group:')&&fresh('nowPlaying') ? data.nowPlaying : {};
  const local=musicReceiver!=='round',name=local?(state.receiver_name||'Echo Display'):'Round Voice';
  const status=state.status||(!local&&data.voice?.music?.status)||'unavailable';
  const speakerReady=local?!!state.available:fresh('voice')&&['armed','muted','cooldown','music'].includes(data.voice?.status);
  const active=!!(group?fresh('groupMusic'):fresh('nowPlaying'))&&speakerReady&&['playing','paused','connected','stopped','idle'].includes(status);
  const trackActive=active&&!!state.title&&['playing','paused'].includes(status);
  const capabilities=state.capabilities||[],has=(name)=>trackActive&&capabilities.includes(name);
  $('track-title').textContent=state.title||'Your next favourite.';
  $('track-artist').textContent=(state.artist||`Choose ${name} from Spotify’s device picker.`).replaceAll('\n',', ');
  $('track-album').textContent=state.album|| (state.title ? 'Spotify' : 'Start something good in Spotify.');
  $('track-explicit').hidden=!state.explicit;
  $('music-status').textContent=!fresh('timers')?'Host unreachable':local?human(status):!fresh('voice')?'Speaker status unavailable':!roundSpeakerConnected()?'Round speaker offline':!speakerReady?'Speaker busy':human(status);$('music-status').classList.toggle('is-playing',active&&status==='playing');
  if(group?.queue_playback&&state.title&&['idle','stopped'].includes(status))$('music-status').textContent='Ready to resume';
  $('play-track').innerHTML=icon(status==='playing'?'pause':'play');$('play-track').setAttribute('aria-label',status==='playing'?'Pause music':'Play music');
  for(const id of ['play-track','previous-track','next-track']){$(id).dataset.requires=group?'groupMusic':local?'nowPlaying':'voice';$(id).dataset.unavailable=String(!active);}
  for(const [id,command] of [['track-seek','seek'],['shuffle-track','shuffle'],['repeat-track','repeat'],['spotify-volume','volume']]){$(id).dataset.requires=group?'groupMusic':'nowPlaying';$(id).dataset.unavailable=String(!has(command));}
  $('spotify-volume').max=group?data.groupMusic.max_volume:100;
  const elapsed=Math.min(state.duration_ms||0,(state.position_ms||0)+(status==='playing'?Math.max(0,Date.now()-((group?received.groupMusic:received.nowPlaying)||Date.now())):0));
  if(!musicDrags.has('track-seek')){$('track-seek').max=String(state.duration_ms||1);$('track-seek').value=String(elapsed);$('track-elapsed').textContent=musicTime(elapsed);}
  $('track-duration').textContent=musicTime(state.duration_ms||0);
  $('track-seek').setAttribute('aria-valuetext',`${musicTime(Number($('track-seek').value))} of ${musicTime(state.duration_ms||0)}`);
  $('shuffle-track').setAttribute('aria-pressed',state.shuffle==null?'mixed':String(state.shuffle));
  $('shuffle-track').title=state.shuffle==null?'Shuffle state unavailable':state.shuffle?'Turn shuffle off':'Turn shuffle on';
  const repeat=state.repeat||'off';$('repeat-track').setAttribute('aria-label',`Repeat: ${state.repeat||'unknown'}`);$('repeat-track').setAttribute('aria-pressed',String(repeat!=='off'));$('repeat-one').hidden=repeat!=='track';
  if(!musicDrags.has('spotify-volume')){$('spotify-volume').value=String(state.volume??0);$('spotify-volume-label').textContent=state.volume==null?'—':`${state.volume}%`;}
  $('music-output-name').textContent=local?name:'Echo round speaker';
  const art=typeof state.artwork==='string'&&/^\/v1\/(?:display\/)?music\/(?:groups\/artwork\/[A-Za-z0-9_:.-]{1,160}|artwork)\/[a-f0-9]{64}$/.test(state.artwork)?state.artwork:'';
  if(art!==coverSource){coverSource=art;const image=$('track-cover');image.hidden=true;$('cover-placeholder').hidden=false;
    image.onload=()=>{if(image.getAttribute('src')===coverSource){image.hidden=false;$('cover-placeholder').hidden=true;}};
    image.onerror=()=>{image.hidden=true;$('cover-placeholder').hidden=false;};
    if(art){image.alt=`${state.album||state.title||'Current track'} cover`;image.src=art;}else image.removeAttribute('src');
  }
  renderDeviceVolume();renderMusicSpeakers();guardButtons();
}
function sendMusic(actionName,value){
  const group=sharedMusicOutput();if(group){if(!group.available||group.blocked)return;let command=actionName;if(command==='toggle')command=group.state==='playing'?(group.features.includes('pause')?'pause':'stop'):'play';return action(()=>api('/v1/music/groups/control',{player:group.id,action:command,value:value??null,revision:data.groupMusic.revision}),'Sent to '+group.name+'.');}
  const ready=fresh('nowPlaying')&&(musicReceiver==='display'?data.nowPlaying.available:fresh('voice')&&['armed','muted','cooldown','music'].includes(data.voice?.status));
  if(!ready||!['playing','paused','connected','stopped'].includes(data.nowPlaying.status))return;
  const route=musicReceiver==='display'?'/v1/display/music/control':'/v1/music/control';return action(()=>api(route,{action:actionName,value}),'Sent to Spotify. Waiting for the receiver’s state.');
}
$('shuffle-track').onclick=()=>sendMusic('shuffle',data.nowPlaying?.shuffle!==true);
$('repeat-track').onclick=()=>{const cycle=['off','context','track'];sendMusic('repeat',cycle[(Math.max(0,cycle.indexOf(data.nowPlaying?.repeat))+1)%3]);};
for(const [id,command,label] of [['track-seek','seek','track-elapsed'],['spotify-volume','volume','spotify-volume-label']]){
  const input=$(id);input.onpointerdown=()=>musicDrags.add(id);input.onkeydown=()=>musicDrags.add(id);
  input.oninput=()=>{$(label).textContent=command==='seek'?musicTime(Number(input.value)):`${input.value}%`;};
  input.onchange=async()=>{const value=Number(input.value);musicDrags.add(id);try{await sendMusic(command,value);}finally{musicDrags.delete(id);}};
  input.onblur=()=>musicDrags.delete(id);input.onpointercancel=()=>musicDrags.delete(id);
  input.onpointerup=()=>{if(!busy)musicDrags.delete(id);};input.onkeyup=()=>{if(!busy)musicDrags.delete(id);};
}
// Output gain is separate from Spotify's stream volume; it also works while paused.
const deviceVolumeCard=document.createElement('div');deviceVolumeCard.className='device-music-volume';
deviceVolumeCard.innerHTML='<label for="music-device-volume">Device speaker level <output id="music-device-level">—</output></label><input id="music-device-volume" type="range" min="0" max="30" step="1" value="0" disabled aria-describedby="music-device-note"><p id="music-device-note" class="tiny soft"></p>';
document.querySelector('.track-column').append(deviceVolumeCard);
function renderDeviceVolume(){
  const group=sharedMusicOutput(),state=data.piAudio,local=musicReceiver==='display',ready=local&&!group&&fresh('piAudio')&&state?.supported&&!!state.settings?.output;
  const input=$('music-device-volume');input.dataset.requires='piAudio';input.dataset.unavailable=String(!ready||!!data.health?.display_demo);
  if(!musicDrags.has('music-device-volume')){input.value=ready?state.settings.volume:0;$('music-device-level').textContent=ready?state.settings.volume+'%':'—';}
  deviceVolumeCard.hidden=!!group;
  $('music-device-note').textContent=!local?'Use the Mini’s physical buttons for its speaker level. Spotify level above controls the stream.':ready?'Music output on this Pi · 0–30%. Voice and call levels are set separately.':'Open Music on the Pi to adjust its attached speaker. This browser’s radio and file volume is in those tabs.';
}
const deviceVolume=$('music-device-volume');
deviceVolume.oninput=()=>{musicDrags.add('music-device-volume');$('music-device-level').textContent=deviceVolume.value+'%';};
deviceVolume.onchange=async()=>{
  const value=Number(deviceVolume.value),receiver=musicReceiver;
  if(receiver!=='display'||!fresh('piAudio')||!data.piAudio?.supported||data.health?.display_demo)return;
  musicDrags.add('music-device-volume');
  try{await action(async()=>{
    // Read just before writing so changing a level cannot restore stale receiver/output settings.
    const latest=await api('/v1/display/music/settings');
    if(musicReceiver!==receiver||!latest.supported)throw Error('Output changed. Please try again.');
    await api('/v1/display/music/settings',{...latest.settings,volume:value},'PUT');
    data.piAudio=await api('/v1/display/music/settings');received.piAudio=Date.now();
  },'Speaker level saved.');}finally{musicDrags.delete('music-device-volume');renderDeviceVolume();}
};
deviceVolume.onpointercancel=deviceVolume.onblur=()=>{if(!busy){musicDrags.delete('music-device-volume');renderDeviceVolume();}};

endpoints.musicDevices='/v1/display/home';pageEndpoints.musicDevices='music';
function renderMusicSpeakers(){
  const speakers=data.home?.speakers||{},choices=speakers.choices||[],entity=choices[speakers.selected]?.entity_id;
  const device=data.musicDevices?.devices?.find(d=>d.entity_id===entity),attrs=device?.attributes||speakers.device?.attributes||{},features=attrs.supported_features||0;
  const available=fresh('home')&&fresh('musicDevices')&&device?.available&&device.access==='control';
  const signature=JSON.stringify([speakers,data.musicDevices,fresh('home'),fresh('musicDevices')]);
  // Keep an active slider/select stable while polling. A changed binding always rebuilds it.
  const host=$('music-speakers');if(host.dataset.entity===entity&&host.contains(document.activeElement)&&document.activeElement.matches('input,select')&&fresh('home')&&fresh('musicDevices'))return;
  if(signature===speakerMusicSignature)return;speakerMusicSignature=signature;host.dataset.entity=entity||'';
  const commands=[['previous','Previous',16],['play','Play',16384],['pause','Pause',1],['next','Next',32],['stop','Stop',4096],['turn_on','Power on',128],['turn_off','Power off',256]];
  host.innerHTML=`<label>Home speaker<select id="music-speaker-choice" data-requires="home" data-unavailable="${!choices.length}">${choices.map((s,i)=>`<option value="${i}" ${i===speakers.selected?'selected':''}>${esc(s.name||s.label||`Speaker ${i+1}`)}${s.available===false?' · offline':''}</option>`).join('')||'<option>No speakers assigned</option>'}</select></label><h3>${esc(attrs.media_title||'Ready when you are.')}</h3><p class="soft">${esc(attrs.media_artist||human(device?.state||speakers.device?.state))}</p><div class="row wrap">${commands.filter(([, ,mask])=>features&mask).map(([command,label])=>`<button class="pill" data-music-speaker="${command}" data-requires="musicDevices" data-unavailable="${!available}">${label}</button>`).join('')}${features&8?`<button class="pill" data-music-speaker="mute" data-requires="musicDevices" data-unavailable="${!available}">${attrs.is_volume_muted?'Unmute':'Mute'}</button>`:''}</div>${features&4?`<label class="room-speaker-volume">Speaker volume <output id="room-speaker-level">${Number.isFinite(attrs.volume_level)?Math.round(attrs.volume_level*100)+'%':'—'}</output><input id="room-speaker-volume" type="range" min="0" max="100" step="1" value="${Math.round((attrs.volume_level||0)*100)}" data-requires="musicDevices" data-unavailable="${!available}"></label>`:''}<p class="tiny soft">${!choices.length?'Assign speakers in Devices to control them here.':!device?'This speaker is not shared with this display. Review its device permissions.':!fresh('musicDevices')?'Speaker status is unavailable. Reconnect to use controls.':!device.available?'Speaker offline.':device.access!=='control'?'Read only. Enable control in device permissions.':'Controls apply to this speaker only. Available actions depend on its integration.'}</p>`;
  $('music-speaker-choice').onchange=event=>{const index=Number(event.target.value),revision=data.home.speakers.revision;event.target.blur();if(fresh('home'))action(()=>api('/v1/home/speakers/select',{index,revision}),'Speaker selected.');};
  // Capture the displayed entity and catalog revision, never a newly selected target.
  const revision=data.musicDevices?.revision,binding=speakers.binding;
  function command(actionName,value=null){
    if(!available||!fresh('home')||!fresh('musicDevices')||binding!==data.home?.speakers?.binding)return;
    return action(()=>api('/v1/display/home/control',{revision,entity_id:entity,action:actionName,value,unit:null}),'Speaker command sent.');
  }
  host.querySelectorAll('[data-music-speaker]').forEach(b=>b.onclick=()=>{if(!b.disabled)command(b.dataset.musicSpeaker,b.dataset.musicSpeaker==='mute'?!attrs.is_volume_muted:null);});
  const slider=$('room-speaker-volume');if(slider){slider.oninput=()=>{$('room-speaker-level').textContent=slider.value+'%';};slider.onchange=async()=>{await command('volume',Number(slider.value));slider.blur();speakerMusicSignature='';renderMusicSpeakers();guardButtons();};}
}

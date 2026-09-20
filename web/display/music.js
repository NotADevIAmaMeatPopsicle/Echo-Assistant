/* Current playback only: no browsing history or track metadata in browser storage. */
'use strict';
let musicReceiver='display';
function musicSnapshotPath(){return musicReceiver==='display'?'/v1/display/music/now-playing':'/v1/music/now-playing';}
$('music-receiver').onchange=()=>{musicReceiver=$('music-receiver').value;delete data.nowPlaying;delete received.nowPlaying;renderMusicPanel();refresh();};
const musicDrags=new Set();let coverSource='',speakerMusicSignature='';
const spotifyPhoneDialog=$('spotify-phone-dialog');
$('spotify-phone-open').onclick=()=>spotifyPhoneDialog.showModal();
$('spotify-phone-close').onclick=()=>spotifyPhoneDialog.close();
document.addEventListener('echo:page',event=>{if(event.detail!=='music'&&spotifyPhoneDialog.open)spotifyPhoneDialog.close();});
function musicTime(ms){const seconds=Math.max(0,Math.floor(ms/1000));return `${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;}
function selectMusicTab(name,focus=false){
  document.querySelectorAll('[data-music-tab]').forEach(button=>{const selected=button.dataset.musicTab===name;button.classList.toggle('selected',selected);button.setAttribute('aria-selected',String(selected));button.tabIndex=selected?0:-1;$(button.getAttribute('aria-controls')).hidden=!selected;if(selected&&focus)button.focus();});
}
document.querySelectorAll('[data-music-tab]').forEach(button=>{
  button.onclick=()=>selectMusicTab(button.dataset.musicTab);
  button.onkeydown=event=>{const names=[...document.querySelectorAll('[data-music-tab]')].filter(b=>!b.hidden).map(b=>b.dataset.musicTab),index=names.indexOf(button.dataset.musicTab);let next;
    if(event.key==='ArrowRight')next=(index+1)%names.length;if(event.key==='ArrowLeft')next=(index+names.length-1)%names.length;if(event.key==='Home')next=0;if(event.key==='End')next=names.length-1;
    if(next!==undefined){event.preventDefault();selectMusicTab(names[next],true);}
  };
});
function renderMusicPanel(){
  const state=fresh('nowPlaying') ? data.nowPlaying : {};
  const local=musicReceiver==='display',name=local?(state.receiver_name||'Echo Display'):'Round Voice';
  const status=state.status||(!local&&data.voice?.music?.status)||'unavailable';
  const speakerReady=local?!!state.available:fresh('voice')&&['armed','muted','cooldown','music'].includes(data.voice?.status);
  const active=!!fresh('nowPlaying')&&speakerReady&&['playing','paused','connected','stopped'].includes(status);
  const trackActive=active&&!!state.title&&['playing','paused'].includes(status);
  const capabilities=state.capabilities||[],has=(name)=>trackActive&&capabilities.includes(name);
  $('track-title').textContent=state.title||'Your next favourite.';
  $('track-artist').textContent=(state.artist||`Choose ${name} from Spotify’s device picker.`).replaceAll('\n',', ');
  $('track-album').textContent=state.album|| (state.title ? 'Spotify' : 'Start something good in Spotify.');
  $('track-explicit').hidden=!state.explicit;
  $('music-status').textContent=!fresh('timers')?'Host unreachable':local?human(status):!fresh('voice')?'Speaker status unavailable':!roundSpeakerConnected()?'Round speaker offline':!speakerReady?'Speaker busy':human(status);$('music-status').classList.toggle('is-playing',active&&status==='playing');
  $('play-track').innerHTML=icon(status==='playing'?'pause':'play');$('play-track').setAttribute('aria-label',status==='playing'?'Pause music':'Play music');
  for(const id of ['play-track','previous-track','next-track']){$(id).dataset.requires=local?'nowPlaying':'voice';$(id).dataset.unavailable=String(!active);}
  for(const [id,command] of [['track-seek','seek'],['shuffle-track','shuffle'],['repeat-track','repeat'],['spotify-volume','volume']]){$(id).dataset.requires='nowPlaying';$(id).dataset.unavailable=String(!has(command));}
  const elapsed=Math.min(state.duration_ms||0,(state.position_ms||0)+(status==='playing'?Math.max(0,Date.now()-(received.nowPlaying||Date.now())):0));
  if(!musicDrags.has('track-seek')){$('track-seek').max=String(state.duration_ms||1);$('track-seek').value=String(elapsed);$('track-elapsed').textContent=musicTime(elapsed);}
  $('track-duration').textContent=musicTime(state.duration_ms||0);
  $('track-seek').setAttribute('aria-valuetext',`${musicTime(Number($('track-seek').value))} of ${musicTime(state.duration_ms||0)}`);
  $('shuffle-track').setAttribute('aria-pressed',state.shuffle==null?'mixed':String(state.shuffle));
  $('shuffle-track').title=state.shuffle==null?'Shuffle state unavailable':state.shuffle?'Turn shuffle off':'Turn shuffle on';
  const repeat=state.repeat||'off';$('repeat-track').setAttribute('aria-label',`Repeat: ${state.repeat||'unknown'}`);$('repeat-track').setAttribute('aria-pressed',String(repeat!=='off'));$('repeat-one').hidden=repeat!=='track';
  if(!musicDrags.has('spotify-volume')){$('spotify-volume').value=String(state.volume??0);$('spotify-volume-label').textContent=state.volume==null?'—':`${state.volume}%`;}
  const deviceVolume=Number(data.voice?.device?.volume);
  $('music-output-note').textContent=local?(state.output_configured?`Audio plays on this Pi. Output level: ${state.output_volume??2}%.`:'Set up this Pi’s Spotify receiver and attached speaker in Settings.'):'Audio plays on the optional round speaker.'+(Number.isFinite(deviceVolume)?` Round volume: ${deviceVolume}%.`:'');
  $('music-output-name').textContent=local?name:'Echo round speaker';
  $('spotify-picker-hint').textContent=`Sign in on your phone, then choose ${name} in Spotify.`;$('spotify-picker-title').textContent=`Choose ${name}.`;$('spotify-phone-destination').textContent=local?'Audio plays on this Pi after its receiver is configured.':'Audio plays on the optional round speaker.';
  const art=typeof state.artwork==='string'&&/^\/v1\/(?:display\/)?music\/artwork\/[a-f0-9]{64}$/.test(state.artwork)?state.artwork:'';
  if(art!==coverSource){coverSource=art;const image=$('track-cover');image.hidden=true;$('cover-placeholder').hidden=false;
    image.onload=()=>{if(image.getAttribute('src')===coverSource){image.hidden=false;$('cover-placeholder').hidden=true;}};
    image.onerror=()=>{image.hidden=true;$('cover-placeholder').hidden=false;};
    if(art){image.alt=`${state.album||state.title||'Current track'} cover`;image.src=art;}else image.removeAttribute('src');
  }
  $('open-spotify').href=/^https:\/\/open\.spotify\.com\/(track|episode)\/[A-Za-z0-9]{22}$/.test(state.open_url||'') ? state.open_url : 'https://open.spotify.com/';
  renderMusicSpeakers();guardButtons();
}
function sendMusic(actionName,value){
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
function renderMusicSpeakers(){
  const speakers=data.home?.speakers||{},signature=JSON.stringify([speakers,fresh('home')]);if(signature===speakerMusicSignature)return;speakerMusicSignature=signature;
  const choices=speakers.choices||[],attrs=speakers.device?.attributes||{},available=fresh('home')&&speakers.status==='available'&&speakers.device?.status==='available';
  $('music-speakers').innerHTML=`<label>Home speaker<select id="music-speaker-choice" data-requires="home" data-unavailable="${!choices.length}">${choices.map((s,i)=>`<option value="${i}" ${i===speakers.selected?'selected':''}>${esc(s.name||s.label||`Speaker ${i+1}`)}${s.available===false?' · offline':''}</option>`).join('')||'<option>No speakers assigned</option>'}</select></label><h3>${esc(attrs.media_title||'Ready when you are.')}</h3><p class="soft">${esc(attrs.media_artist||human(speakers.device?.state))}</p><div class="row wrap">${[['play','Play'],['pause','Pause'],['down','Volume −'],['up','Volume +'],[attrs.is_volume_muted?'unmute':'mute',attrs.is_volume_muted?'Unmute':'Mute']].map(([command,label])=>`<button class="pill" data-speaker="${command}" data-requires="home" data-unavailable="${!available}">${label}</button>`).join('')}</div><p class="tiny soft">${Number.isFinite(attrs.volume_level)?`Volume ${Math.round(attrs.volume_level*100)}% · `:''}Controls use your assigned Home Assistant speaker.</p>`;
  $('music-speaker-choice').onchange=event=>{if(fresh('home'))action(()=>api('/v1/home/speakers/select',{index:Number(event.target.value),revision:data.home.speakers.revision}),'Speaker selected.');};
}

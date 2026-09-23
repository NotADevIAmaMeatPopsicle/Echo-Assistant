/* YouTube selection controls. Provider resources live only in the native lease player. */
(()=>{
  'use strict';
  const base='/v1/display/video',validID=value=>typeof value==='string'&&/^[A-Za-z0-9_-]{11}$/.test(value);
  const card=document.createElement('article');card.id='video-provider-card';card.className='card video-provider-card';card.hidden=true;
  card.innerHTML='<div class="video-provider-mark" aria-hidden="true"><svg viewBox="0 0 48 36"><rect x="1" y="2" width="46" height="32" rx="10"/><path d="m20 11 13 7-13 7z"/></svg></div><div class="video-provider-copy"><span class="eyebrow">YOUTUBE</span><h2>A moment to watch.</h2><p id="video-provider-status" class="soft" role="status">Checking the selected video…</p><div class="video-provider-actions"><button type="button" class="pill primary" id="video-provider-start" disabled>Load selected video</button><button type="button" class="pill" id="video-provider-stop" disabled>Stop video</button><a class="text-button" id="video-provider-handoff" target="_blank" rel="noopener noreferrer" aria-disabled="true" tabindex="-1">Watch on YouTube ↗</a><button type="button" class="pill" id="video-provider-share" disabled>Copy video link</button><button type="button" class="pill" id="video-provider-choose" hidden>Choose video</button><button type="button" class="text-button" id="video-provider-refresh">Refresh</button></div><p class="tiny soft">Loads Google’s official player in a separate screen. Starts muted; use YouTube’s controls to play. Loading contacts Google and may show ads.</p></div>';
  $('page-music').append(card);
  const settings=document.createElement('article');settings.id='video-provider-settings';settings.className='card';settings.hidden=true;
  settings.innerHTML='<span class="eyebrow">YOUTUBE · OWNER SETTINGS</span><h2>Choose a video to share.</h2><p class="soft">Select one ordinary YouTube video and the household displays that may load it. Saving never starts playback.</p><button type="button" class="pill" id="video-provider-configure">Video & displays</button><form id="video-provider-form" hidden><label class="check-label"><input type="checkbox" id="video-provider-enabled">Enable selected video</label><label>YouTube link or video ID<input id="video-provider-id" maxlength="2048" autocomplete="off" spellcheck="false" placeholder="https://www.youtube.com/watch?v=…"></label><p class="tiny soft">Paste a YouTube watch, Shorts or youtu.be link, or an 11-character video ID. Leave blank to clear the selection. No account connection or paid library is included.</p><fieldset><legend>Allow these Household displays</legend><div id="video-provider-displays"></div></fieldset><button type="submit" class="pill primary" id="video-provider-save">Save video settings</button></form><p class="tiny soft" role="status" id="video-provider-settings-status"></p>';
  $('page-settings').append(settings);
  const dialog=document.createElement('dialog');dialog.id='video-provider-phone';
  dialog.innerHTML='<span class="eyebrow">CONTINUE ON YOUR PHONE</span><h2>Watch on YouTube.</h2><p class="soft">Open this address on your phone in YouTube or your browser. Sign-in, age, region and purchase requirements are handled by YouTube.</p><label>Video address<input id="video-provider-url" readonly autocomplete="off"></label><div class="row"><button type="button" class="pill primary" id="video-provider-copy">Copy link</button><button type="button" class="pill" id="video-provider-close">Close</button></div><p class="tiny soft" role="status" id="video-provider-copy-status"></p>';
  document.body.append(dialog);
  let generation=0,identity='',selection=null,output=null,config=null,loading=false,pending=false,configBusy=false,lastRead=0,readSerial=0;
  function stamp(){const s=data.session;if(!s||signInRequired||s.profile?.mode==='guest'||s.profile?.personal||s.member)return '';return JSON.stringify([s.role,s.receiver_id||'',s.profile_revision||0]);}
  function current(version,who){return version===generation&&who===identity&&who===stamp()&&!!who;}
  function status(message){$('video-provider-status').textContent=message;}
  function reset(){generation++;readSerial++;identity='';selection=output=config=null;loading=pending=configBusy=false;lastRead=0;card.hidden=settings.hidden=true;$('video-provider-form').hidden=true;$('video-provider-save').disabled=false;$('video-provider-id').value='';$('video-provider-displays').replaceChildren();$('video-provider-url').value='';$('video-provider-copy-status').textContent='';$('video-provider-settings-status').textContent='';if(dialog.open)dialog.close();render();}
  function render(){
    const active=identity&&identity===stamp(),ready=active&&selection?.available&&validID(selection.video_id),preview=data.health?.display_demo===true;
    card.hidden=!active;settings.hidden=!active||data.session?.role!=='owner';
    $('video-provider-start').disabled=!ready||!output?.available||pending||preview;
    $('video-provider-stop').disabled=!active||pending||preview||!output||['idle','stopped','unavailable','disabled'].includes(output.phase);
    const link=$('video-provider-handoff');link.setAttribute('aria-disabled',String(!ready));link.tabIndex=ready?0:-1;
    if(ready)link.href='https://www.youtube.com/watch?v='+selection.video_id;else link.removeAttribute('href');
    $('video-provider-share').disabled=!ready;
    $('video-provider-choose').hidden=!active||data.session?.role!=='owner';
    $('video-provider-refresh').disabled=loading||pending;
    $('video-provider-configure').disabled=configBusy;
    if(!active)return;
    if(preview)status('Preview only · loading and playback are disabled.');
    else if(!selection)status('Video status is unavailable. Check the connection to your Echo host.');
    else if(!ready){const reasons={disabled:'Video is off. The owner can choose a video in Settings.',display_not_allowed:'The owner has not shared video with this display.',guest_not_allowed:'Video is unavailable in Guest mode.',personal_not_allowed:'Return to Household mode to use video.',mini_not_allowed:'Video is available on supported displays.'};status(reasons[selection.reason]||'No video selected. The owner can choose one in Settings.');}
    else if(!output?.available){const reasons={video_not_allowed:'Share this video with this display in Settings before loading it.',spotify:'Pause Spotify, then refresh to load the video.',focus:'Echo is using audio. Try again when it finishes.'};status(reasons[output?.error]||'The separate video player is unavailable here. Watch on YouTube opens the selected video in your browser.');}
    else if(['starting','active','playing','ready','paused'].includes(output.phase))status('Video screen open · use its Stop & back button to return. Audio is limited to 2% on this display.');
    else status('Ready when you are. Starts muted; this display limits audio to 2%.');
  }
  async function refreshVideo(force=false){
    const who=stamp();if(!who)return;
    if(identity!==who){reset();identity=who;}
    if(loading||(!force&&Date.now()-lastRead<5000))return;
    const version=generation,serial=++readSerial;loading=true;lastRead=Date.now();
    const results=await Promise.allSettled([api(base),api(base+'/output')]);
    if(serial!==readSerial||!current(version,who))return;
    loading=false;
    const next=results[0].status==='fulfilled'?results[0].value:null;
    if(next&&next.profile_revision!==undefined&&next.profile_revision!==(data.session.profile_revision||0)){selection=output=null;render();return;}
    if(selection&&(!next||next.revision!==selection.revision||next.video_id!==selection.video_id||!next.available)){
      generation++;pending=configBusy=false;config=null;$('video-provider-form').hidden=true;$('video-provider-save').disabled=false;if(dialog.open)dialog.close();$('video-provider-url').value='';
    }
    selection=next;output=results[1].status==='fulfilled'?results[1].value:null;render();
  }
  async function command(action){
    if(pending||!identity||identity!==stamp()||data.health?.display_demo)return;
    if(action==='start'&&(!selection?.available||!validID(selection.video_id)||!output?.available))return;
    const version=generation,who=identity,revision=selection?.revision;pending=true;render();status(action==='start'?'Opening the video screen…':'Stopping video…');
    try{const result=await api(base+'/output',action==='start'?{action,revision}:{action});if(!current(version,who)||revision!==selection?.revision)return;output=result;pending=false;render();await refreshVideo(true);}
    catch(error){if(current(version,who)){pending=false;render();status(error.message);}}
  }
  async function configure(){
    if(configBusy||data.session?.role!=='owner'||!stamp())return;
    if(identity!==stamp()){reset();identity=stamp();}
    const version=generation,who=identity;configBusy=true;render();$('video-provider-settings-status').textContent='Loading your video settings…';
    try{
      const [value,displays]=await Promise.all([api(base+'/settings'),api('/v1/displays')]);
      if(!current(version,who)||data.session?.role!=='owner')return;
      config=value;$('video-provider-enabled').checked=!!value.enabled;$('video-provider-id').value=validID(value.video_id)?value.video_id:'';
      const eligible=(displays.items||[]).filter(d=>d.profile?.mode==='household'&&!d.profile?.personal);
      $('video-provider-displays').innerHTML=eligible.map(d=>`<label class="check-label"><input type="checkbox" value="${esc(d.id)}" ${(value.allowed_display_ids||[]).includes(d.id)?'checked':''}><span>${esc(d.name)}</span></label>`).join('')||'<p class="tiny soft">No Household displays paired yet.</p>';
      $('video-provider-form').hidden=false;$('video-provider-settings-status').textContent='Only selected Household displays can load this video. Personal and Guest sessions cannot use it.';
    }catch(error){if(current(version,who))$('video-provider-settings-status').textContent=error.message;}
    finally{if(current(version,who)){configBusy=false;render();}}
  }
  function parseVideoID(value){
    if(!value||validID(value))return value;
    try{const url=new URL(value);if(!['https:','http:'].includes(url.protocol)||url.username||url.password)return null;
      const host=url.hostname.toLowerCase(),parts=url.pathname.split('/');let id;
      if(host==='youtu.be')id=parts[1];
      else if(['youtube.com','www.youtube.com','m.youtube.com','music.youtube.com'].includes(host))id=url.pathname==='/watch'?url.searchParams.get('v'):['shorts','embed','live'].includes(parts[1])?parts[2]:null;
      return validID(id)?id:null;
    }catch{return null;}
  }
  async function save(event){
    event.preventDefault();if(configBusy||!config||data.session?.role!=='owner'||!stamp())return;
    const video_id=parseVideoID($('video-provider-id').value.trim()),allowed_display_ids=[...$('video-provider-displays').querySelectorAll('input:checked')].map(input=>input.value);
    if(video_id===null){$('video-provider-settings-status').textContent='Enter a valid YouTube link or an 11-character video ID.';return;}
    if(allowed_display_ids.length>32){$('video-provider-settings-status').textContent='Choose up to 32 displays.';return;}
    const version=generation,who=identity;configBusy=true;$('video-provider-save').disabled=true;
    try{const result=await api(base+'/settings',{revision:config.revision,enabled:$('video-provider-enabled').checked,video_id,allowed_display_ids},'PUT');
      if(!current(version,who)||data.session?.role!=='owner')return;
      config=result;generation++;readSerial++;loading=pending=false;selection=null;if(dialog.open)dialog.close();$('video-provider-url').value='';$('video-provider-settings-status').textContent='Saved. Loading a video still requires an explicit tap.';configBusy=false;$('video-provider-save').disabled=false;await refreshVideo(true);
    }catch(error){if(current(version,who))$('video-provider-settings-status').textContent=error.status===409?'Video settings changed. Load Video & displays again before saving.':error.message;}
    finally{if(current(version,who)){configBusy=false;$('video-provider-save').disabled=false;render();}}
  }
  function observe(){const who=stamp();if(identity!==who){reset();identity=who;render();}if(who&&!$('page-music').hidden)void refreshVideo();}
  $('video-provider-start').onclick=()=>void command('start');$('video-provider-stop').onclick=()=>void command('stop');
  $('video-provider-configure').onclick=()=>void configure();$('video-provider-form').onsubmit=save;
  $('video-provider-share').onclick=()=>{if(identity!==stamp()||!selection?.available||!validID(selection.video_id))return;$('video-provider-url').value='https://www.youtube.com/watch?v='+selection.video_id;$('video-provider-copy-status').textContent='';dialog.showModal();};
  $('video-provider-copy').onclick=async()=>{const version=generation,who=identity;try{await navigator.clipboard.writeText($('video-provider-url').value);if(current(version,who)&&dialog.open)$('video-provider-copy-status').textContent='Link copied. Open it on your phone.';}catch{if(current(version,who)&&dialog.open){$('video-provider-url').select();$('video-provider-copy-status').textContent='Select and copy the address, then open it on your phone.';}}};
  $('video-provider-handoff').onclick=event=>{if(identity!==stamp()||!selection?.available||!validID(selection.video_id))event.preventDefault();};
  $('video-provider-choose').onclick=()=>{if(window.EchoSettings.open('music',settings))void configure();};
  $('video-provider-refresh').onclick=()=>void refreshVideo(true);
  $('video-provider-close').onclick=()=>dialog.close();
  document.addEventListener('echo:page',()=>{if(dialog.open)dialog.close();observe();});
  extensions.push(observe);setInterval(observe,1000);
  // Hiding the main kiosk must not cancel the separate native player.
  window.EchoVideo={refresh:()=>refreshVideo(true),reset};
})();

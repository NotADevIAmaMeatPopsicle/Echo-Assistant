/* The Pi bridge serves only indexed files beneath ~/Music/Echo. */
(()=>{
  'use strict';
  const card=document.createElement('article');card.className='card';
  card.innerHTML='<div class="row spread wrap"><div><span class="eyebrow">ON THE SD CARD</span><h2>Your music, right here.</h2></div><button id="device-library-rescan" class="pill">Rescan</button></div><p id="device-library-status" class="soft" role="status">Opening this display’s music folder…</p><p class="tiny soft">Copy songs and folders into <code>~/Music/Echo</code> on the Pi. M3U / M3U8 playlists use relative file paths. New files appear automatically.</p><div class="library-filters"><label>Find a song<input id="device-library-search" type="search" placeholder="Song or filename"></label><label>Folder<select id="device-library-folder"><option value="">All folders</option></select></label><label>Playlist<select id="device-library-playlist"><option value="">All songs</option></select></label></div><div class="row wrap"><button id="device-library-queue" class="pill primary" disabled>Queue these songs</button><button id="device-library-play" class="pill" disabled>Play these songs</button><button id="device-library-shuffle" class="pill" disabled>Shuffle</button></div><div id="device-library-tracks" class="library-results"></div><button id="device-library-more" class="pill" hidden>Show more</button>';
  $('files-panel').prepend(card);
  let library=null,shown=[],limit=50,busy=false,serial=0,signature='',identity='';
  function permitted(){return !signInRequired&&data.session?.profile?.mode!=='guest';}
  function draw(){
    const query=$('device-library-search').value.toLowerCase(),folder=$('device-library-folder').value,playlist=library?.playlists.find(p=>p.id===$('device-library-playlist').value);
    const map=new Map((library?.tracks||[]).map(t=>[t.id,t]));
    const tracks=playlist?playlist.tracks.map(id=>map.get(id)).filter(Boolean):[...map.values()];
    shown=tracks.filter(t=>(!folder||t.folder===folder)&&(!query||(t.name+' '+t.filename).toLowerCase().includes(query)));
    $('device-library-tracks').innerHTML=shown.slice(0,limit).map((t,i)=>`<article class="library-item"><div class="library-monogram" aria-hidden="true">♪</div><div class="library-item-text"><strong>${esc(t.name)}</strong><span class="tiny soft">${esc(t.folder||'Music / Echo')} · ${(t.size/1048576).toFixed(1)} MB</span></div><button class="pill" data-sd-queue="${i}">+ Queue</button><button class="pill primary" data-sd-play="${i}" ${data.health?.display_demo?'disabled':''}>Play</button></article>`).join('')||'<p class="soft">'+(library?.supported?'No songs here yet. Add music to the folder above, or choose files below.':'Choose files below to listen from this browser.')+'</p>';
    $('device-library-more').hidden=shown.length<=limit;
    for(const id of ['queue','play','shuffle'])$('device-library-'+id).disabled=!shown.length||!permitted()||!!data.health?.display_demo;
  }
  async function load(force=false){
    if(busy||!permitted())return;busy=true;const request=serial;
    try{const value=await api('/v1/display/library'+(force?'?rescan=1':''));if(request!==serial)return;library=value;
      $('device-library-status').textContent=value.supported?`${value.tracks.length} songs · ${value.playlists.length} playlists${Number.isFinite(value.free_bytes)?' · '+(value.free_bytes/1073741824).toFixed(1)+' GB free':''}${value.truncated?' · Library limit reached':''}`:value.message;
      const next=JSON.stringify([value.revision,value.playlists]);if(next!==signature){signature=next;const folder=$('device-library-folder').value,playlist=$('device-library-playlist').value;
        $('device-library-folder').innerHTML='<option value="">All folders</option>'+[...new Set(value.tracks.map(t=>t.folder).filter(Boolean))].sort().map(f=>`<option value="${esc(f)}">${esc(f)}</option>`).join('');$('device-library-folder').value=folder;
        $('device-library-playlist').innerHTML='<option value="">All songs</option>'+value.playlists.map(p=>`<option value="${p.id}">${esc(p.name)} (${p.tracks.length})${p.missing?' · missing files':''}</option>`).join('');$('device-library-playlist').value=playlist;draw();}
    }catch(error){if(request===serial)$('device-library-status').textContent=error.message;}finally{busy=false;}
  }
  function queue(tracks,{replace=false,play=false,shuffle=false}={}){
    if(!permitted()||data.health?.display_demo)return;
    tracks=tracks.filter(t=>/^\/v1\/display\/library\/stream\/[a-f0-9]{32}$/.test(t.url));
    if(shuffle){tracks=[...tracks];for(let i=tracks.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[tracks[i],tracks[j]]=[tracks[j],tracks[i]];}}
    if(replace){stopDisplayMedia();mediaSource=null;mediaQueue=[];queueIndex=-1;}
    const start=mediaQueue.length;mediaQueue.push(...tracks.slice(0,1000-start));
    if(mediaQueue.length===start)return;
    if(play||!mediaSource)loadMedia({kind:'file',index:start,name:mediaQueue[start].name});else renderMediaQueue();
    if(play)void playDisplayMedia();else toast(`${mediaQueue.length-start} song(s) queued.`);
  }
  $('device-library-tracks').onclick=e=>{const play=e.target.closest('[data-sd-play]'),add=e.target.closest('[data-sd-queue]');if(play)queue([shown[Number(play.dataset.sdPlay)]],{replace:true,play:true});if(add)queue([shown[Number(add.dataset.sdQueue)]]);};
  $('device-library-queue').onclick=()=>queue(shown);
  $('device-library-play').onclick=()=>queue(shown,{replace:true,play:true});
  $('device-library-shuffle').onclick=()=>queue(shown,{replace:true,play:true,shuffle:true});
  for(const id of ['search','folder','playlist'])$('device-library-'+id).addEventListener(id==='search'?'input':'change',()=>{limit=50;draw();});
  $('device-library-more').onclick=()=>{limit+=50;draw();};
  $('device-library-rescan').onclick=()=>void load(true);
  document.addEventListener('echo:music-tab',e=>{if(e.detail==='files')void load();});
  setInterval(()=>{if(!$('page-music').hidden&&!$('files-panel').hidden)void load();},15000);
  extensions.push(()=>{const next=JSON.stringify([signInRequired,data.session?.role,data.session?.receiver_id,data.session?.profile_revision,data.session?.member]);if(next!==identity){identity=next;serial++;library=null;signature='';draw();}});
})();

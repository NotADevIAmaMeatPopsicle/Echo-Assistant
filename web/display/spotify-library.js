(()=>{
  'use strict';
  const card=document.createElement('article');card.className='card spotify-library-card';
  card.innerHTML='<div class="row spread wrap"><div><span class="eyebrow">YOUR SPOTIFY</span><h2>Your listening shelf.</h2></div><button id="spotify-account-connect" class="pill">Connect account</button></div><p id="spotify-account-status" class="soft" role="status">Open your playlists, albums and saved music.</p><p id="spotify-account-note" class="tiny soft">Sign in once through Music Assistant. The connection stays on your Echo host, including after a restart. Spotify Premium is required.</p><div class="library-filters"><label>Play on<select id="spotify-library-output"><option value="">Choose a shared output</option></select></label><button id="spotify-library-browse" class="pill">All music</button><button id="spotify-library-queue" class="pill">Queue</button></div><div class="row spotify-shelf-tabs" aria-label="Spotify library"><button id="spotify-library-playlists" class="pill" aria-pressed="true">Playlists</button><button id="spotify-library-podcasts" class="pill" aria-pressed="false">Podcasts</button></div><div id="spotify-podcast-tools" class="row spread wrap" hidden><button id="spotify-new-episodes" class="pill">New episodes</button><label>Show order<select id="spotify-podcast-sort"><option value="name">Podcast name</option><option value="latest">Latest aired episode</option></select></label></div><form id="spotify-library-search" class="row wrap"><label class="grow">Find music<input id="spotify-library-query" type="search" maxlength="120" placeholder="Song, artist, album or playlist" required></label><button class="pill primary" type="submit">Search</button></form><p id="spotify-library-status" class="tiny soft" role="status"></p><div id="spotify-library-items" class="library-results"></div><button id="spotify-library-more" class="pill" hidden>More playlists</button><p class="tiny soft">Play replaces the selected output’s queue. Use Together for its playback controls and room grouping. You can still send music from the Spotify app using Spotify Connect.</p>';
  $('spotify-panel').append(card);
  $('spotify-library-more').after($('spotify-library-search'));
  const dialog=document.createElement('dialog');dialog.id='spotify-setup-dialog';
  dialog.innerHTML='<div class="row spread"><span class="eyebrow">CONNECT SPOTIFY</span><button id="spotify-setup-close" class="pill">Close</button></div><h2 id="spotify-setup-title">Spotify sign-in</h2><p id="spotify-setup-description" class="soft"></p><p id="spotify-setup-progress" class="soft" role="status"></p><a id="spotify-setup-link" class="pill primary" target="_blank" rel="noopener noreferrer" hidden>Continue to Spotify</a><form id="spotify-setup-form" hidden><div id="spotify-setup-fields"></div><button class="pill primary" type="submit">Continue</button></form><p class="tiny soft">Complete the steps here after approving Spotify in the new tab. Tokens stay in Music Assistant’s persistent storage.</p><button id="spotify-setup-cancel" class="text-button">Cancel connection setup</button>';
  document.body.append(dialog);
  let rows=[],request=0,identity='',outputs='',accountLoaded=false,step=null,stepSignature='',setupBusy=false;
  let shelf={view:'browse',collection:'playlists',selection:null,sort:'name',offset:0},more=null,pollTimer=null,connected=false,autoLoaded='',pending=false;
  function output(){return data.groupMusic?.items.find(p=>p.id===$('spotify-library-output').value&&p.available&&!p.blocked&&!p.in_group);}
  function visible(){return !signInRequired&&!$('page-music').hidden&&!$('spotify-panel').hidden;}
  async function account(){try{const result=await api('/v1/music/spotify');accountLoaded=true;connected=result.connected;card.classList.toggle('is-connected',connected);$('spotify-account-status').textContent=result.message;$('spotify-account-connect').textContent=result.configured?'Reconnect account':'Connect account';}catch(error){$('spotify-account-status').textContent=error.message;}}
  function dates(value){if(!value)return '';const d=new Date(value);return Number.isNaN(d.getTime())?'':d.toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'});}
  function draw(){
    $('spotify-library-items').classList.toggle('spotify-pinned',shelf.collection==='playlists'&&rows.length<=3);
    $('spotify-library-items').innerHTML=rows.map((r,i)=>{
      const open=['folder','podcast'].includes(r.kind),date=dates(r.release_date);
      const details=r.kind==='podcast'?(r.latest_episode?`Latest: ${r.latest_episode}`:r.publisher):r.podcast||r.artist||'';
      return `<article class="library-item"><span class="library-monogram" aria-hidden="true">${r.kind==='podcast'?'◉':r.kind==='podcast_episode'?'▶':r.kind==='playlist'?String(i+1).padStart(2,'0'):'♫'}</span><div class="library-item-text"><span class="tiny soft">${esc(r.current?'PLAYING':human(r.kind))}${date?' · '+esc(date):''}</span><strong>${esc(r.name)}</strong>${details?`<span class="tiny soft">${esc(details)}</span>`:''}</div><button class="pill ${open?'':'primary'}" data-spotify-item="${i}" ${r.available&&r.selection?'':'disabled'}>${r.kind==='podcast'?'Episodes':open?'Open':'Play'}</button></article>`;
    }).join('');
  }
  function tabs(){
    const podcasts=['podcasts','new_episodes'].includes(shelf.collection);
    $('spotify-library-playlists').setAttribute('aria-pressed',String(shelf.collection==='playlists'));
    $('spotify-library-podcasts').setAttribute('aria-pressed',String(podcasts));
    $('spotify-podcast-tools').hidden=!podcasts;
    $('spotify-new-episodes').setAttribute('aria-pressed',String(shelf.collection==='new_episodes'));
    $('spotify-podcast-sort').disabled=shelf.collection!=='podcasts'||!!shelf.selection;
  }
  async function listing(view='browse',selection=null,options={}){
    const p=output();if(!p)return toast('Choose an available shared output first.');
    clearTimeout(pollTimer);const serial=++request,id=p.id;
    shelf={view,selection,collection:options.collection||'library',sort:options.sort||'name',offset:options.offset||0};tabs();
    more=null;$('spotify-library-more').hidden=true;
    if(!options.append&&!options.quiet){rows=[];draw();$('spotify-library-status').textContent='Loading Spotify…';}
    try{
      const value=await api('/v1/music/groups/library',{player:id,...shelf,source:'spotify',query:view==='search'?$('spotify-library-query').value:''},'POST',AbortSignal.timeout(20000));
      if(serial!==request||output()?.id!==id)return;
      rows=options.append?[...rows,...value.items]:value.items;draw();pending=!!value.pending;
      more=value.more?value.next_offset??(shelf.offset+value.items.length):null;
      $('spotify-library-more').hidden=more===null||pending;
      $('spotify-library-more').textContent=shelf.collection==='playlists'?'More playlists':'Load more';
      let note=shelf.collection==='playlists'?'Your top playlists, ready to play.':shelf.collection==='new_episodes'?'Newest releases from followed shows. Completed episodes are hidden when listening history is available.':shelf.collection==='podcasts'?(selection?'Episodes, newest first.':'Your followed podcasts.'):'Choose a folder, playlist, album or song.';
      if(!rows.length&&!pending)note=view==='queue'?'This queue is empty.':shelf.collection==='new_episodes'?'No new episodes are available.':'Nothing here yet. Try another view or search.';
      if(pending)note+=' Checking episode dates…';
      if(value.unavailable_shows)note+=` ${value.unavailable_shows} show${value.unavailable_shows===1?' is':'s are'} temporarily unavailable.`;
      if(value.truncated)note+=' Latest releases cover the first 64 followed shows.';
      $('spotify-library-status').textContent=note;
      if(pending)pollTimer=setTimeout(()=>{if(serial===request&&visible())void listing(view,selection,{...shelf,quiet:true});},2500);
    }catch(error){if(serial===request){pending=false;$('spotify-library-status').textContent=error.message;}}
  }
  function openShelf(collection){autoLoaded=output()?.id||'';void listing('browse',null,{collection,sort:collection==='podcasts'?$('spotify-podcast-sort').value:'latest'});}
  $('spotify-library-playlists').onclick=()=>openShelf('playlists');
  $('spotify-library-podcasts').onclick=()=>openShelf('podcasts');
  $('spotify-new-episodes').onclick=()=>openShelf('new_episodes');
  $('spotify-podcast-sort').onchange=()=>openShelf('podcasts');
  $('spotify-library-more').onclick=()=>{if(more!==null)void listing(shelf.view,shelf.selection,{...shelf,offset:more,append:true});};
  $('spotify-library-browse').onclick=()=>void listing();$('spotify-library-queue').onclick=()=>void listing('queue');
  $('spotify-library-search').onsubmit=e=>{e.preventDefault();void listing('search');};
  $('spotify-library-output').onchange=()=>{request++;rows=[];draw();autoLoaded='';clearTimeout(pollTimer);};
  $('spotify-library-items').onclick=e=>{const b=e.target.closest('[data-spotify-item]'),p=output();if(!b||!p)return;const row=rows[Number(b.dataset.spotifyItem)];if(!row)return;
    if(['folder','podcast'].includes(row.kind))return void listing('browse',row.selection,{collection:row.kind==='podcast'?'podcasts':'library',sort:'latest'});
    b.disabled=true;void action(async()=>{await api('/v1/music/groups/library/play',{player:p.id,selection:row.selection});chooseSharedMusic(p.id);await refresh();await listing('queue');},'Playback requested on '+p.name+'.');
  };
  function renderStep(value){
    step=value;$('spotify-setup-title').textContent=value.title||'Connect Spotify';$('spotify-setup-description').textContent=value.description||'';$('spotify-setup-progress').textContent=value.error||value.progress_text||value.reason||'';
    const next=JSON.stringify(value);if(next===stepSignature)return;stepSignature=next;
    $('spotify-setup-link').hidden=!value.url;if(value.url)$('spotify-setup-link').href=value.url;else $('spotify-setup-link').removeAttribute('href');
    $('spotify-setup-form').hidden=value.type!=='form';
    $('spotify-setup-fields').innerHTML=(value.entries||[]).map(e=>{const label=esc(e.label||human(e.key)),val=e.value??e.default_value;
      if(e.type==='boolean')return `<label class="check-label"><input data-spotify-field="${esc(e.key)}" type="checkbox" ${val?'checked':''}>${label}</label>`;
      if(e.options?.length)return `<label>${label}<select data-spotify-field="${esc(e.key)}">${e.options.map(o=>`<option value="${esc(o.value)}" ${o.value===val?'selected':''}>${esc(o.title||human(o.value))}</option>`).join('')}</select></label>`;
      return `<label>${label}<input data-spotify-field="${esc(e.key)}" type="text" autocomplete="off" maxlength="4096" ${e.required?'required':''} value="${esc(val||'')}"></label>`;
    }).join('');
    if(value.type==='finish'){void account();$('spotify-setup-progress').textContent='Connected. Your Spotify library is ready to browse.';openShelf('playlists');}
  }
  async function poll(){if(!dialog.open||setupBusy||['finish','abort'].includes(step?.type))return;setupBusy=true;try{renderStep(await api('/v1/music/spotify/setup'));}catch(error){$('spotify-setup-progress').textContent=error.message;}finally{setupBusy=false;}}
  $('spotify-account-connect').onclick=async()=>{dialog.showModal();step=null;stepSignature='';setupBusy=true;try{try{const current=await api('/v1/music/spotify/setup');if(['finish','abort'].includes(current.type)){await api('/v1/music/spotify/setup',{},'DELETE');renderStep(await api('/v1/music/spotify/setup',{}));}else renderStep(current);}catch(error){renderStep(await api('/v1/music/spotify/setup',{}));}}catch(error){$('spotify-setup-progress').textContent=error.message;}finally{setupBusy=false;}};
  $('spotify-setup-form').onsubmit=async e=>{e.preventDefault();if(setupBusy)return;setupBusy=true;const values={};for(const el of $('spotify-setup-fields').querySelectorAll('[data-spotify-field]'))values[el.dataset.spotifyField]=el.type==='checkbox'?el.checked:el.value;try{renderStep(await api('/v1/music/spotify/setup/step',{step:step.step_id,values}));}catch(error){$('spotify-setup-progress').textContent=error.message;}finally{setupBusy=false;}};
  $('spotify-setup-close').onclick=()=>dialog.close();
  $('spotify-setup-cancel').onclick=()=>void action(async()=>{await api('/v1/music/spotify/setup',{},'DELETE');dialog.close();step=null;},'Spotify setup closed.');
  setInterval(()=>void poll(),2500);
  document.addEventListener('echo:music-tab',e=>{if(e.detail==='spotify'){void account();if(pending&&output())void listing(shelf.view,shelf.selection,{...shelf,quiet:true});}});
  extensions.push(()=>{
    const next=JSON.stringify([signInRequired,data.session?.role,data.session?.receiver_id,data.session?.profile_revision,data.session?.member]);
    if(next!==identity){card.classList.remove('is-connected');identity=next;request++;rows=[];outputs='';accountLoaded=false;connected=false;autoLoaded='';pending=false;clearTimeout(pollTimer);dialog.close();step=null;$('spotify-library-items').replaceChildren();}
    $('spotify-account-connect').hidden=data.session?.role!=='owner';
    if(!accountLoaded&&!signInRequired&&!$('page-music').hidden&&!$('spotify-panel').hidden){accountLoaded=true;void account();}
    const available=(data.groupMusic?.items||[]).filter(p=>p.available&&!p.blocked&&!p.in_group),signature=JSON.stringify(available.map(p=>[p.id,p.name]));
    if(signature!==outputs){outputs=signature;const selected=$('spotify-library-output').value;$('spotify-library-output').innerHTML='<option value="">Choose a shared output</option>'+available.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');$('spotify-library-output').value=available.some(p=>p.id===selected)?selected:available.length===1?available[0].id:'';}
    if(visible()&&connected&&fresh('groupMusic')&&output()&&autoLoaded!==output().id){autoLoaded=output().id;openShelf('playlists');}
    for(const el of [$('spotify-library-playlists'),$('spotify-library-podcasts'),$('spotify-new-episodes'),$('spotify-library-browse'),$('spotify-library-queue'),...$('spotify-library-search').querySelectorAll('button')])el.disabled=!fresh('groupMusic')||!output()||!!data.health?.display_demo;
  });
})();

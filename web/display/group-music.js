/* Group controls use Music Assistant; audio never passes through this page. */
(()=>{
  'use strict';
  const tab=document.createElement('button');tab.id='tab-groups';tab.role='tab';tab.dataset.musicTab='groups';tab.setAttribute('aria-controls','groups-panel');tab.setAttribute('aria-selected','false');tab.tabIndex=-1;tab.textContent='Together';
  document.querySelector('.music-tabs').append(tab);tab.onclick=()=>selectMusicTab('groups');
  tab.onkeydown=event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const buttons=[...document.querySelectorAll('[data-music-tab]')].filter(b=>!b.hidden),i=buttons.indexOf(tab),next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(i+(event.key==='ArrowRight'?1:buttons.length-1))%buttons.length;selectMusicTab(buttons[next].dataset.musicTab,true);}};
  const panel=document.createElement('section');panel.id='groups-panel';panel.hidden=true;panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',tab.id);
  panel.innerHTML='<article class="card group-music-intro"><span class="eyebrow">ONE SOUND, MORE ROOMS</span><h2>Better together.</h2><p id="group-music-status" class="soft">Connect Music Assistant in Settings to choose compatible speakers.</p><p class="tiny soft">Choose the player with your music, then add compatible outputs. Grouping a playing source can start sound in those rooms.</p></article><div id="group-music-players" class="group-music-players"></div>';
  $('page-music').append(panel);
  const settings=document.createElement('article');settings.className='card';settings.id='group-music-settings';settings.hidden=true;
  settings.innerHTML='<span class="eyebrow">MUSIC ASSISTANT</span><h2>Bring your rooms together.</h2><p class="soft">Connect a private Music Assistant server, then share the outputs Echo may control. Grouping support depends on the players and their protocols.</p><button class="pill" type="button" id="group-music-load">Connection & outputs</button><form id="group-music-form" hidden><label class="check-label"><input id="group-music-enabled" type="checkbox">Enable grouped music</label><label>Private server URL<input id="group-music-url" type="url" maxlength="200" placeholder="http://echo-music:8095"></label><label>Access token<input id="group-music-token" type="password" autocomplete="off" maxlength="4096" placeholder="Leave blank to keep a saved token"></label><label>Provider setup token (optional)<input id="group-music-setup-token" type="password" autocomplete="off" maxlength="4096" placeholder="Music Assistant admin token; leave blank to keep saved"></label><p class="tiny soft">Used only by owner-managed Spotify account setup. Normal playback uses the access token above.</p><label>Maximum volume control<input id="group-music-max" type="number" min="1" max="100" value="30"></label><p class="tiny soft">This limits new volume commands. It does not lower an amplifier or a player’s existing volume automatically.</p><div id="group-music-receivers"></div><fieldset class="group-mini-settings"><legend>Echo Mini</legend><p id="group-mini-status" class="tiny soft" role="status"></p><label class="check-label"><input id="group-mini-enabled" type="checkbox">Enable the Mini music receiver</label><p class="tiny soft">Requires Mini firmware 0.16.0 and the optional host runtime. Once connected, load outputs below and share the Mini to use its music controls.</p><label>Player name<input id="group-mini-name" maxlength="60" value="Echo Mini"></label><label>Speaker volume ceiling (%)<input id="group-mini-volume" type="number" min="0" max="20" value="2"></label><p class="tiny soft">Starts at 2%. The speaker also respects its physical volume setting. Voice, calls, alerts and Spotify take priority on this Mini.</p><details><summary>Timing calibration</summary><label>Advance playback (milliseconds)<input id="group-mini-latency" type="number" min="-200" max="200" value="0"></label><p class="tiny soft">Leave at zero until measured against another speaker. Positive values compensate for extra output delay.</p></details></fieldset><button class="pill primary" type="submit">Save connection</button><button class="pill" type="button" id="group-music-discover">Load outputs</button><p id="group-music-setting-status" role="status" class="tiny soft"></p><div id="group-music-output-choices"></div><button class="pill" type="button" id="group-music-share" disabled>Save shared outputs</button></form>';
  $('page-settings').append(settings);let config=null,groupEdit=null,signature='';
  const dialog=document.createElement('dialog');dialog.id='group-music-dialog';
  dialog.innerHTML='<form id="group-members-form"><span class="eyebrow">CHOOSE YOUR ROOMS</span><h2 id="group-members-title"></h2><p class="soft">Selected speakers join this player. Unchecking a current member removes it. No other groups are moved automatically.</p><div id="group-members-options"></div><p id="group-members-status" class="tiny soft" role="status"></p><div class="row"><button class="pill" type="button" id="group-members-cancel">Cancel</button><button class="pill primary" type="submit" id="group-members-save">Apply group</button></div></form>';
  document.body.append(dialog);$('group-members-cancel').onclick=()=>dialog.close();
  endpoints.groupMusic='/v1/music/groups';pageEndpoints.groupMusic='music';
  endpoints.groupLocal='/v1/display/group-music';pageEndpoints.groupLocal='settings';
  function draw(){
    const guest=data.session?.profile?.mode==='guest';settings.hidden=data.session?.role!=='owner';tab.hidden=guest;
    const mini=data.voice?.grouped_music,transport=mini?.transport;
    $('group-mini-status').textContent=!roundSpeakerConnected()?'Mini is not connected. Its receiver stays off.':data.voice?.device?.timed_audio!=='1'?'Install Mini firmware 0.16.0 to enable synchronized music.':!mini?'Mini receiver status is unavailable.':mini.phase==='runtime_required'?'Install the optional grouped-music runtime on the host.':mini.phase==='disabled'?'Mini receiver is disabled.':mini.connected?(mini.server_clock&&transport?.clock_synchronized?(mini.focus_held?'Connected · quiet while another source uses the speaker':'Connected · clocks synchronized'):'Connected · synchronizing clocks'):'Mini receiver: '+human(mini.phase);
    if(guest&&tab.getAttribute('aria-selected')==='true')selectMusicTab('spotify');
    if(guest&&dialog.open)dialog.close();
    const state=data.groupMusic,usable=fresh('groupMusic')&&state?.status==='available';
    $('group-music-status').textContent=!fresh('groupMusic')?'Grouped music is unavailable. Check the host and Music Assistant connection.':state.status==='not_configured'?'Connect Music Assistant in Settings, then share the outputs you want here.':!state.items.length?'No outputs shared yet. Add players in Music Assistant, then select them in Echo Settings.':'Players and current group membership from your private Music Assistant server.';
    const rows=state?.items||[],nextSignature=JSON.stringify([state,usable]);
    if(signature===nextSignature)return;
    const focused=document.activeElement,range=focused?.matches('[data-group-volume]');
    if(range&&usable)return;
    const focusPlayer=focused?.closest('[data-group-player]')?.dataset.groupPlayer,focusCommand=focused?.dataset.groupCommand;
    signature=nextSignature;
    $('group-music-players').innerHTML=rows.map(p=>{
      const active=usable&&p.available&&!p.blocked,group=p.features.includes('set_members')&&!p.in_group;
      return `<article class="card group-player" data-group-player="${esc(p.id)}"><div class="row spread"><h3>${esc(p.name)}</h3><span class="tiny soft">${esc(p.available?human(p.state):'Offline')}</span></div><p class="soft">${esc(p.title||'Ready for music')}${p.artist?' · '+esc(p.artist):''}</p><p class="tiny soft">${p.leader?'With '+esc(rows.find(x=>x.id===p.leader)?.name||'another player'):p.members.length?'Together: '+esc(p.members.map(id=>rows.find(x=>x.id===id)?.name||id).join(', ')):'Playing independently'}</p>${p.blocked?'<p class="tiny soft">This group includes an output not shared with Echo. Review it in Music Assistant.</p>':''}<div class="row group-transport">${[['previous','Previous'],[p.state==='playing'?(p.features.includes('pause')?'pause':'stop'):'play',p.state==='playing'?(p.features.includes('pause')?'Pause':'Stop'):'Play'],['next','Next'],...(p.state==='playing'&&!p.features.includes('pause')?[]:[['stop','Stop']])].map(([cmd,label])=>`<button class="pill" type="button" data-group-command="${cmd}" ${active?'':'disabled'}>${label}</button>`).join('')}</div><div class="row">${p.features.includes('volume_set')?`<label class="group-volume">Volume <output>${p.volume??'—'}%</output><input aria-label="${esc(p.name)} volume" data-group-volume type="range" min="0" max="${state.max_volume}" value="${Math.min(p.volume||0,state.max_volume)}" ${active?'':'disabled'}></label>`:''}${p.features.includes('volume_mute')?`<button type="button" class="pill" data-group-mute ${active?'':'disabled'}>${p.muted?'Unmute':'Mute'}</button>`:''}${group?`<button type="button" class="pill primary" data-group-edit ${active?'':'disabled'}>Choose rooms</button>`:''}</div></article>`;
    }).join('');
    if(focusPlayer&&focusCommand){const card=[...panel.querySelectorAll('[data-group-player]')].find(c=>c.dataset.groupPlayer===focusPlayer);card?.querySelector(`[data-group-command="${focusCommand}"]`)?.focus({preventScroll:true});}
  }
  // Preserve a dragged slider, but refresh stale controls and access restrictions.
  extensions.push(draw);
  panel.addEventListener('focusout',()=>setTimeout(draw,0));
  document.addEventListener('echo:page',event=>{if(event.detail!=='music'&&dialog.open)dialog.close();});
  async function command(player,action,value=null){await api('/v1/music/groups/control',{player,action,value,revision:data.groupMusic.revision});delete data.groupMusic;await refresh();draw();}
  panel.addEventListener('change',event=>{if(event.target.matches('[data-group-volume]'))action(()=>command(event.target.closest('[data-group-player]').dataset.groupPlayer,'volume',Number(event.target.value)),'Volume sent.');});
  panel.addEventListener('click',event=>{
    const row=event.target.closest('[data-group-player]');if(!row||!fresh('groupMusic'))return;
    const player=data.groupMusic.items.find(p=>p.id===row.dataset.groupPlayer);if(!player)return;
    if(event.target.matches('[data-group-command]'))return action(()=>command(player.id,event.target.dataset.groupCommand),'Music command sent.');
    if(event.target.matches('[data-group-mute]'))return action(()=>command(player.id,'mute',!player.muted),'Mute command sent.');
    if(event.target.matches('[data-group-edit]')){
      groupEdit={leader:player.id,revision:data.groupMusic.revision,binding:data.groupMusic.binding};$('group-members-title').textContent='Play with '+player.name;
      const options=data.groupMusic.items.filter(p=>p.id!==player.id&&(player.compatible.includes(p.id)||player.members.includes(p.id)));
      $('group-members-options').innerHTML=options.map(p=>`<label class="check-label"><input type="checkbox" value="${esc(p.id)}" ${player.members.includes(p.id)?'checked':''} ${player.members.includes(p.id)||(p.available&&!p.blocked&&!p.in_group)?'':'disabled'}><span>${esc(p.name)}${p.available?'':' · Offline'}${p.leader&&p.leader!==player.id?' · In another group':''}</span></label>`).join('')||empty('No compatible outputs are shared. Add another compatible player in Music Assistant.');
      $('group-members-status').textContent='Review the rooms before applying. A playing source may become audible in newly added rooms.';$('group-members-save').disabled=false;dialog.showModal();
    }
  });
  $('group-members-form').onsubmit=async event=>{event.preventDefault();if(!groupEdit)return;$('group-members-save').disabled=true;
    try{const result=await api('/v1/music/groups/members',{...groupEdit,members:[...$('group-members-options').querySelectorAll('input:checked')].map(el=>el.value)});dialog.close();toast(result.text);delete data.groupMusic;await refresh();draw();}
    catch(error){$('group-members-status').textContent=error.message;$('group-members-save').disabled=false;}
  };
  $('group-music-load').onclick=()=>action(async()=>{config=await api('/v1/music/groups/settings');const displays=await api('/v1/displays');$('group-music-receivers').innerHTML='<p class="soft">Allow these paired displays to receive grouped audio:</p>'+displays.items.filter(d=>d.profile?.mode!=='guest').map(d=>`<label class="check-label"><input type="checkbox" value="${esc(d.id)}" ${(config.config.receivers||[]).includes(d.id)?'checked':''}><span>${esc(d.name)}</span></label>`).join('');$('group-music-output-choices').replaceChildren();$('group-music-share').disabled=true;$('group-music-enabled').checked=config.config.enabled;$('group-music-url').value=config.config.url;$('group-music-max').value=config.config.max_volume;$('group-music-token').value='';$('group-music-setup-token').value='';$('group-mini-enabled').checked=!!config.config.round_enabled;$('group-mini-name').value=config.config.round_name||'Echo Mini';$('group-mini-volume').value=config.config.round_volume??2;$('group-mini-latency').value=config.config.round_latency_ms??0;$('group-music-form').hidden=false;$('group-music-setting-status').textContent=config.token_saved?'Token saved privately on the host.':'Create an access token in your private Music Assistant server.';},'Connection settings loaded.');
  async function save(values,token=null,setup_token=null){config=await api('/v1/music/groups/settings',{revision:config.revision,config:values,token,setup_token},'PUT');$('group-music-token').value='';$('group-music-setup-token').value='';$('group-music-share').disabled=true;$('group-music-output-choices').replaceChildren();delete data.groupMusic;await refresh();draw();}
  $('group-music-form').onsubmit=event=>{event.preventDefault();if(config)action(()=>save({...config.config,enabled:$('group-music-enabled').checked,url:$('group-music-url').value.trim(),max_volume:Number($('group-music-max').value),round_enabled:$('group-mini-enabled').checked,round_name:$('group-mini-name').value.trim(),round_volume:Number($('group-mini-volume').value),round_latency_ms:Number($('group-mini-latency').value),receivers:[...$('group-music-receivers').querySelectorAll('input:checked')].map(el=>el.value)},$('group-music-token').value||null,$('group-music-setup-token').value||null),'Music connection saved.');};
  $('group-music-discover').onclick=()=>action(async()=>{const state=await api('/v1/music/groups/discovery');$('group-music-output-choices').innerHTML=state.items.map(p=>`<label class="check-label"><input type="checkbox" value="${esc(p.id)}" ${config.config.players.includes(p.id)?'checked':''}><span>${esc(p.name)}${p.available?'':' · Offline'}</span></label>`).join('')||empty('No players found. Add compatible players in Music Assistant first.');$('group-music-share').disabled=false;},'Outputs loaded.');
  $('group-music-share').onclick=()=>{if(config)action(()=>save({...config.config,players:[...$('group-music-output-choices').querySelectorAll('input:checked')].map(i=>i.value)}),'Shared outputs saved.');};
  const local=document.createElement('article');local.id='group-local-settings';local.className='card';local.hidden=true;
  local.innerHTML='<span class="eyebrow">THIS DISPLAY</span><h2>Join the music.</h2><p class="soft">Play synchronized music through this display’s attached speaker. The owner must also allow it under Music Assistant.</p><p id="group-local-status" class="soft" role="status"></p><form id="group-local-form"><label class="check-label"><input id="group-local-enabled" type="checkbox">Enable grouped playback</label><label>Player name<input id="group-local-name" maxlength="60" required></label><label>Attached output<select id="group-local-output"></select></label><label>Output ceiling<input id="group-local-volume" type="number" min="0" max="30" required></label><p class="tiny soft">Voice lowers or silences only this display. Spotify playing here takes priority; other rooms continue.</p><button class="pill primary" type="submit">Save player</button></form>';
  $('page-settings').append(local);let localSignature='';
  extensions.push(()=>{
    const value=data.groupLocal;local.hidden=!fresh('groupLocal')||!value?.supported||data.session?.profile?.mode==='guest';
    if(local.hidden)return;
    $('group-local-status').textContent=value.error||(value.installed?human(value.state?.phase)+(value.state?.clock_synchronized?' · Clock synchronized':''):'Install the optional grouped-music runtime to use this output.');
    const signature=JSON.stringify([value.config,value.outputs,value.installed]);if(signature===localSignature||local.contains(document.activeElement))return;localSignature=signature;
    $('group-local-enabled').checked=value.config.enabled;$('group-local-enabled').disabled=!value.installed;
    $('group-local-name').value=value.config.name;$('group-local-volume').value=value.config.volume;
    $('group-local-output').innerHTML='<option value="">Choose the attached speaker</option>'+value.outputs.map(o=>`<option value="${esc(o.id)}" ${o.id===value.config.output?'selected':''}>${esc(o.name)}</option>`).join('');
  });
  $('group-local-form').onsubmit=event=>{event.preventDefault();action(async()=>{
    await api('/v1/display/group-music',{enabled:$('group-local-enabled').checked,name:$('group-local-name').value,output:$('group-local-output').value,volume:Number($('group-local-volume').value)},'PUT');
    delete data.groupLocal;await refresh();
  },'Player settings saved.');};

})();

/* Library browsing keeps provider credentials and media URLs on the host. */
(()=>{
  'use strict';
  const dialog=document.createElement('dialog');dialog.id='group-library-dialog';
  dialog.innerHTML='<div class="row spread"><span class="eyebrow">MUSIC ASSISTANT</span><button type="button" class="pill" id="group-library-close">Close</button></div><h2 id="group-library-title">Choose music</h2><p id="group-library-destination" class="soft"></p><div class="row"><button type="button" class="pill" id="group-library-root">Sources</button><button type="button" class="pill" id="group-library-queue">Queue</button></div><form id="group-library-search" class="row"><label>Find music<input type="search" id="group-library-query" maxlength="120" placeholder="Song, artist, album or playlist" required></label><button type="submit" class="pill primary">Search</button></form><p id="group-library-status" class="tiny soft" role="status"></p><div id="group-library-items"></div><div class="row" id="group-library-pages" hidden><button type="button" class="pill" id="group-library-prev">Previous 50</button><button type="button" class="pill" id="group-library-next">Next 50</button></div><p class="tiny soft">Play now replaces this output’s queue and starts its connected rooms. Browsing alone does not play sound.</p>';
  document.body.append(dialog);
  let player=null,listing=null,serial=0;
  function close(){serial++;player=null;listing=null;dialog.close();$('group-library-items').replaceChildren();$('group-library-query').value='';}
  $('group-library-close').onclick=close;
  dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
  document.addEventListener('echo:page',event=>{if(event.detail!=='music'&&dialog.open)close();});
  function current(){return fresh('groupMusic')&&data.session?.profile?.mode!=='guest'&&data.groupMusic?.items.find(p=>p.id===player&&p.available&&!p.blocked&&!p.in_group);}
  extensions.push(()=>{
    if(dialog.open&&!current())close();
    document.querySelectorAll('[data-group-player]').forEach(card=>{
      const value=data.groupMusic?.items.find(p=>p.id===card.dataset.groupPlayer);
      if(!card.querySelector('[data-group-library]')){
        const row=document.createElement('div');row.className='row';
        row.innerHTML='<button type="button" class="pill primary" data-group-library="browse">Choose music</button><button type="button" class="pill" data-group-library="queue">Queue</button>';
        card.append(row);
      }
      card.querySelectorAll('[data-group-library]').forEach(b=>b.disabled=!fresh('groupMusic')||!value?.available||value.blocked||value.in_group||data.session?.profile?.mode==='guest');
    });
  });
  async function load(view='browse',selection=null,offset=0){
    if(!current())return close();
    const generation=++serial,identifier=player;
    listing=null;$('group-library-items').replaceChildren();$('group-library-pages').hidden=true;$('group-library-status').textContent='Loading music…';
    try{
      const result=await api('/v1/music/groups/library',{player:identifier,view,selection,query:view==='search'?$('group-library-query').value:'',offset});
      if(generation!==serial||!dialog.open||!current())return;
      listing=result;
      $('group-library-items').innerHTML=result.items.map((item,index)=>`<article class="group-library-item"><div><span class="tiny soft">${esc(item.current?'PLAYING':human(item.kind))}</span><strong>${esc(item.name)}</strong>${item.artist?'<span class="soft">'+esc(item.artist)+'</span>':''}</div><button type="button" class="pill ${item.kind==='folder'?'':'primary'}" data-library-index="${index}" ${item.selection&&item.available?'':'disabled'}>${item.kind==='folder'?'Open':item.kind==='queue'?'Play this':'Play now'}</button></article>`).join('');
      $('group-library-status').textContent=result.items.length?(result.truncated?'Showing the first 100 entries. Search to narrow your choice.':view==='queue'?`${result.total} queued · showing ${offset+1}–${offset+result.items.length}`:'Choose a folder or play a selection.'):
        view==='queue'?'This queue is empty. Choose Sources or search for music.':view==='search'?'No matching music. Try another name or connect a provider in Music Assistant.':'No music sources to browse. Connect a provider or music library in Music Assistant first.';
      $('group-library-pages').hidden=view!=='queue'||(!result.more&&!offset);$('group-library-prev').disabled=!offset;$('group-library-next').disabled=!result.more;
    }catch(error){if(generation===serial)$('group-library-status').textContent=error.message;}
  }
  $('groups-panel').addEventListener('click',event=>{
    const button=event.target.closest('[data-group-library]');if(!button||button.disabled)return;
    player=button.closest('[data-group-player]').dataset.groupPlayer;const value=current();if(!value)return;
    $('group-library-title').textContent='Music for '+value.name;
    $('group-library-destination').textContent=value.members.length?'Also playing in: '+value.members.map(id=>data.groupMusic.items.find(p=>p.id===id)?.name||'shared output').join(', '):'Playing on this output.';
    dialog.showModal();load(button.dataset.groupLibrary);
  });
  $('group-library-root').onclick=()=>load();$('group-library-queue').onclick=()=>load('queue');
  $('group-library-search').onsubmit=event=>{event.preventDefault();load('search');};
  $('group-library-prev').onclick=()=>load('queue',null,Math.max(0,(listing?.offset||0)-50));
  $('group-library-next').onclick=()=>load('queue',null,(listing?.offset||0)+50);
  $('group-library-items').onclick=async event=>{
    const button=event.target.closest('[data-library-index]'),item=listing?.items[Number(button?.dataset.libraryIndex)];
    if(!button||button.disabled||!item?.selection||!current())return;
    if(item.kind==='folder')return load('browse',item.selection);
    const generation=++serial,identifier=player;
    $('group-library-items').querySelectorAll('button').forEach(b=>b.disabled=true);$('group-library-status').textContent='Requesting playback…';
    try{
      const result=await api('/v1/music/groups/library/play',{player:identifier,selection:item.selection});
      if(generation!==serial||!dialog.open)return;
      toast(result.text);await refresh();if(dialog.open)load('queue');
    }catch(error){if(generation===serial)$('group-library-status').textContent=error.message+' Reload Sources or Queue before retrying.';}
  };
})();

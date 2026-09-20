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
  settings.innerHTML='<span class="eyebrow">MUSIC ASSISTANT</span><h2>Bring your rooms together.</h2><p class="soft">Connect a private Music Assistant server, then share the outputs Echo may control. Grouping support depends on the players and their protocols.</p><button class="pill" type="button" id="group-music-load">Connection & outputs</button><form id="group-music-form" hidden><label class="check-label"><input id="group-music-enabled" type="checkbox">Enable grouped music</label><label>Private server URL<input id="group-music-url" type="url" maxlength="200" placeholder="http://echo-music:8095"></label><label>Access token<input id="group-music-token" type="password" autocomplete="off" maxlength="4096" placeholder="Leave blank to keep a saved token"></label><label>Maximum volume control<input id="group-music-max" type="number" min="1" max="100" value="30"></label><p class="tiny soft">This limits new volume commands. It does not lower an amplifier or a player’s existing volume automatically.</p><button class="pill primary" type="submit">Save connection</button><button class="pill" type="button" id="group-music-discover">Load outputs</button><p id="group-music-setting-status" role="status" class="tiny soft"></p><div id="group-music-output-choices"></div><button class="pill" type="button" id="group-music-share" disabled>Save shared outputs</button></form>';
  $('page-settings').append(settings);let config=null,groupEdit=null,signature='';
  const dialog=document.createElement('dialog');dialog.id='group-music-dialog';
  dialog.innerHTML='<form id="group-members-form"><span class="eyebrow">CHOOSE YOUR ROOMS</span><h2 id="group-members-title"></h2><p class="soft">Selected speakers join this player. Unchecking a current member removes it. No other groups are moved automatically.</p><div id="group-members-options"></div><p id="group-members-status" class="tiny soft" role="status"></p><div class="row"><button class="pill" type="button" id="group-members-cancel">Cancel</button><button class="pill primary" type="submit" id="group-members-save">Apply group</button></div></form>';
  document.body.append(dialog);$('group-members-cancel').onclick=()=>dialog.close();
  endpoints.groupMusic='/v1/music/groups';pageEndpoints.groupMusic='music';
  function draw(){
    const guest=data.session?.profile?.mode==='guest';settings.hidden=data.session?.role!=='owner';tab.hidden=guest;
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
      return `<article class="card group-player" data-group-player="${esc(p.id)}"><div class="row spread"><h3>${esc(p.name)}</h3><span class="tiny soft">${esc(p.available?human(p.state):'Offline')}</span></div><p class="soft">${esc(p.title||'Ready for music')}${p.artist?' · '+esc(p.artist):''}</p><p class="tiny soft">${p.leader?'With '+esc(rows.find(x=>x.id===p.leader)?.name||'another player'):p.members.length?'Together: '+esc(p.members.map(id=>rows.find(x=>x.id===id)?.name||id).join(', ')):'Playing independently'}</p>${p.blocked?'<p class="tiny soft">This group includes an output not shared with Echo. Review it in Music Assistant.</p>':''}<div class="row group-transport">${[['previous','Previous'],[p.state==='playing'?'pause':'play',p.state==='playing'?'Pause':'Play'],['next','Next'],['stop','Stop']].map(([cmd,label])=>`<button class="pill" type="button" data-group-command="${cmd}" ${active?'':'disabled'}>${label}</button>`).join('')}</div><div class="row">${p.features.includes('volume_set')?`<label class="group-volume">Volume <output>${p.volume??'—'}%</output><input aria-label="${esc(p.name)} volume" data-group-volume type="range" min="0" max="${state.max_volume}" value="${Math.min(p.volume||0,state.max_volume)}" ${active?'':'disabled'}></label>`:''}${p.features.includes('volume_mute')?`<button type="button" class="pill" data-group-mute ${active?'':'disabled'}>${p.muted?'Unmute':'Mute'}</button>`:''}${group?`<button type="button" class="pill primary" data-group-edit ${active?'':'disabled'}>Choose rooms</button>`:''}</div></article>`;
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
  $('group-music-load').onclick=()=>action(async()=>{config=await api('/v1/music/groups/settings');$('group-music-output-choices').replaceChildren();$('group-music-share').disabled=true;$('group-music-enabled').checked=config.config.enabled;$('group-music-url').value=config.config.url;$('group-music-max').value=config.config.max_volume;$('group-music-token').value='';$('group-music-form').hidden=false;$('group-music-setting-status').textContent=config.token_saved?'Token saved privately on the host.':'Create an access token in your private Music Assistant server.';},'Connection settings loaded.');
  async function save(values,token=null){config=await api('/v1/music/groups/settings',{revision:config.revision,config:values,token},'PUT');$('group-music-token').value='';$('group-music-share').disabled=true;$('group-music-output-choices').replaceChildren();delete data.groupMusic;await refresh();draw();}
  $('group-music-form').onsubmit=event=>{event.preventDefault();if(config)action(()=>save({...config.config,enabled:$('group-music-enabled').checked,url:$('group-music-url').value.trim(),max_volume:Number($('group-music-max').value)},$('group-music-token').value||null),'Music connection saved.');};
  $('group-music-discover').onclick=()=>action(async()=>{const state=await api('/v1/music/groups/discovery');$('group-music-output-choices').innerHTML=state.items.map(p=>`<label class="check-label"><input type="checkbox" value="${esc(p.id)}" ${config.config.players.includes(p.id)?'checked':''}><span>${esc(p.name)}${p.available?'':' · Offline'}</span></label>`).join('')||empty('No players found. Add compatible players in Music Assistant first.');$('group-music-share').disabled=false;},'Outputs loaded.');
  $('group-music-share').onclick=()=>{if(config)action(()=>save({...config.config,players:[...$('group-music-output-choices').querySelectorAll('input:checked')].map(i=>i.value)}),'Shared outputs saved.');};
})();

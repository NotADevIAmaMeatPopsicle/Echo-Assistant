/* Owner-managed display profiles. The API enforces every grant independently. */
(()=>{
  'use strict';
  const dialog=document.createElement('dialog');dialog.id='display-access-dialog';
  dialog.innerHTML='<form id="display-access-form"><div class="row spread"><div><span class="eyebrow">SHARE INTENTIONALLY</span><h2 id="display-access-title">Display access</h2></div><button type="button" class="icon-button" id="display-access-close" aria-label="Close display access">×</button></div><div id="display-access-scroll"><div class="two-columns"><label>Profile name<input id="display-access-name" maxlength="60" required></label><label>Room<input id="display-access-room" maxlength="60" placeholder="Optional"></label></div><label>Access level<select id="display-access-mode"><option value="household">Household · trusted shared device</option><option value="guest">Guest · only selected devices and sources</option></select></label><p class="tiny soft" id="display-access-description"></p><div id="display-access-guest" hidden><label class="check-label"><input type="checkbox" id="display-access-conversation">Allow guest conversation and public web lookup</label><p class="tiny soft">Uses the configured model with separate, temporary conversation history. Household memory, lists, routines, photos and Hermes tools are not shared. Guest home actions use the approved controls on Rooms.</p><h3>Home devices</h3><div id="display-access-devices"></div><div id="display-access-sources" class="access-sources"></div></div></div><p id="display-access-status" role="status"></p><div class="row spread"><button type="button" class="pill" id="display-access-cancel">Cancel</button><button class="pill primary" type="submit" id="display-access-save">Save access</button></div></form>';
  document.body.append(dialog);let editing=null,epoch=0;
  const badge=document.createElement('span');badge.id='display-profile-badge';badge.hidden=true;$('connection').before(badge);
  const note=document.createElement('div');note.id='guest-display-note';note.hidden=true;note.textContent='Only devices shared with this display appear below. Use their controls to make changes.';$('page-rooms').prepend(note);
  function mode(){const guest=$('display-access-mode').value==='guest';$('display-access-guest').hidden=!guest;$('display-access-description').textContent=guest?'Choose the devices and read-only sources available here. No room is shared automatically.':'Household displays can use shared memory, lists, plans and the assistant’s granted tools. Choose this only for a trusted device.';}
  $('display-access-mode').onchange=mode;
  for(const id of ['display-access-close','display-access-cancel'])$(id).onclick=()=>dialog.close();
  dialog.addEventListener('close',()=>{epoch++;editing=null;});
  document.addEventListener('echo:edit-display-access',async event=>{
    const version=++epoch,d=event.detail;editing=null;$('display-access-save').disabled=true;
    const profile=d.profile||{mode:'household',name:'Household',room:'',conversation:true,home_devices:{},calendars:[],cameras:[],presence_sensors:[]};
    $('display-access-title').textContent=d.name;$('display-access-name').value=profile.name;$('display-access-room').value=profile.room;
    $('display-access-mode').value=profile.mode;$('display-access-conversation').checked=profile.conversation;mode();
    $('display-access-devices').replaceChildren();$('display-access-sources').replaceChildren();$('display-access-status').textContent='Loading shared devices and sources…';dialog.showModal();
    try{
      const [home,sources]=await Promise.all([api('/v1/display/home'),api('/v1/display/source-settings')]);
      if(version!==epoch||!dialog.open)return;
      const devices=(home.devices||[]).filter(i=>['light','switch','climate','media_player','weather'].includes(i.domain));
      for(const entity of Object.keys(profile.home_devices||{}))if(!devices.some(d=>d.entity_id===entity))devices.push({entity_id:entity,name:entity,access:profile.home_devices[entity],available:false});
      $('display-access-devices').innerHTML=devices.map(i=>`<label class="access-device"><span>${esc(i.name)}<small>${esc(i.area||'No room assigned')}${i.available?'':' · unavailable'}</small></span><select data-profile-entity="${esc(i.entity_id)}"><option value="">Not shared</option><option value="read">View</option>${i.access==='control'?'<option value="control">View & control</option>':''}</select></label>`).join('')||empty('No devices are shared with Echo yet. Configure them on Devices.');
      dialog.querySelectorAll('[data-profile-entity]').forEach(el=>el.value=profile.home_devices?.[el.dataset.profileEntity]||'');
      for(const [key,label] of [['calendars','Read-only calendars'],['cameras','Cameras'],['presence_sensors','Presence wake sensors']]){
        const section=document.createElement('section');section.innerHTML=`<h3>${label}</h3>`;
        for(const entity of sources.sources?.[key]||[]){const item=(sources.items||[]).find(i=>i.entity_id===entity);const row=document.createElement('label');row.className='check-label';const check=document.createElement('input');check.type='checkbox';check.dataset.profileSource=key;check.value=entity;check.checked=(profile[key]||[]).includes(entity);row.append(check,document.createTextNode(item?.name||entity));section.append(row);}
        if(section.children.length===1){const p=document.createElement('p');p.className='tiny soft';p.textContent='No sources shared in Display settings.';section.append(p);}
        $('display-access-sources').append(section);
      }
      editing={id:d.id,revision:d.profile_revision||0};$('display-access-status').textContent='Changes apply to this paired display. Switching profiles clears its conversation.';$('display-access-save').disabled=false;
    }catch(error){if(version===epoch)$('display-access-status').textContent=error.message;}
  });
  $('display-access-form').onsubmit=async event=>{
    event.preventDefault();if(!editing)return;const target=editing,version=epoch;$('display-access-save').disabled=true;
    const profile={mode:$('display-access-mode').value,name:$('display-access-name').value.trim(),room:$('display-access-room').value.trim(),conversation:$('display-access-conversation').checked,home_devices:{},calendars:[],cameras:[],presence_sensors:[]};
    dialog.querySelectorAll('[data-profile-entity]').forEach(el=>{if(el.value)profile.home_devices[el.dataset.profileEntity]=el.value;});
    dialog.querySelectorAll('[data-profile-source]:checked').forEach(el=>profile[el.dataset.profileSource].push(el.value));
    try{await api('/v1/displays/'+target.id+'/profile',{revision:target.revision,profile},'PUT');if(version!==epoch)return;dialog.close();pairingListAt=0;await loadPairedDisplays();toast('Display access saved.');}
    catch(error){if(version===epoch){$('display-access-status').textContent=error.message;$('display-access-save').disabled=false;}}
  };
  let accessVersion=null;
  extensions.push(()=>{
    const session=data.session;if(!session)return;
    const version=(session.receiver_id||'owner')+':'+(session.profile_revision||0);
    if(accessVersion!==null&&accessVersion!==version){document.body.style.visibility='hidden';clearVoiceReply();void closeMic();location.reload();return;}
    accessVersion=version;const profile=session.profile,guest=session.role==='display'&&profile?.mode==='guest';
    document.body.classList.toggle('guest-display',guest);note.hidden=!guest;badge.hidden=!guest;
    if(guest){
      badge.textContent='Guest · '+profile.name+(profile.room?' · '+profile.room:'');
      const welcome=$('chat-welcome');
      if(welcome&&!welcome.dataset.guest){
        welcome.dataset.guest='true';welcome.querySelector('p').textContent='Ask a question or explore an idea. Your household’s private information stays separate.';
        const examples=[['Explain something','Why does the Moon have phases?'],['Find an idea','Suggest a simple vegetarian dinner'],['Explore with Echo','What can you help a guest with?']];
        welcome.querySelectorAll('[data-prompt]').forEach((button,i)=>{button.textContent=examples[i][0];button.dataset.prompt=examples[i][1];});
      }
      window.echoAllowedPages=new Set(['home','rooms','music','timers','day','settings',...(profile.conversation?['assistant']:[])]);
      document.querySelectorAll('[data-page=assistant]').forEach(el=>el.hidden=!profile.conversation);
      if(!profile.conversation){$('send-chat').disabled=true;$('voice-start').disabled=true;}
      if(typeof musicReceiver!=='undefined'&&musicReceiver!=='display'){musicReceiver='display';$('music-receiver').value='display';delete data.nowPlaying;delete received.nowPlaying;}
      if(!window.echoAllowedPages.has(location.hash.slice(1)))page('home');
      const permission=$('allow-home');if(permission){permission.checked=false;permission.closest('label').hidden=true;}
    }else window.echoAllowedPages=null;
  });
})();

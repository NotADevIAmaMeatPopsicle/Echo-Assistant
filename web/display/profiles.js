/* Owner-managed display profiles. The API enforces every grant independently. */
(()=>{
  'use strict';
  const dialog=document.createElement('dialog');dialog.id='display-access-dialog';
  dialog.innerHTML='<form id="display-access-form"><div class="row spread"><div><span class="eyebrow">SHARE INTENTIONALLY</span><h2 id="display-access-title">Display access</h2></div><button type="button" class="icon-button" id="display-access-close" aria-label="Close display access">×</button></div><div id="display-access-scroll"><div class="two-columns"><label>Profile name<input id="display-access-name" maxlength="60" required></label><label>Room<input id="display-access-room" maxlength="60" placeholder="Optional"></label></div><label>Access level<select id="display-access-mode"><option value="household">Household · trusted shared device</option><option value="guest">Guest · only selected devices and sources</option></select></label><p class="tiny soft" id="display-access-description"></p><div id="display-access-guest" hidden><label class="check-label"><input type="checkbox" id="display-access-conversation">Allow guest conversation and public web lookup</label><p class="tiny soft">Uses the configured model with separate, temporary conversation history. Household memory, lists, routines, photos and Hermes tools are not shared. Guest home actions stay within the selected devices.</p><label class="check-label"><input type="checkbox" id="display-access-home-voice">Allow local guest home voice commands</label><p class="tiny soft" id="display-access-voice-note">Off by default. Supports named-device and shared-room commands without sending device data to a model. Home actions still need permission for the message or the owner’s wake-word setting.</p><h3>Home devices</h3><div id="display-access-devices"></div><div id="display-access-sources" class="access-sources"></div></div><section id="display-access-members"><h3>Personal sign-in</h3><p class="tiny soft">Choose who can unlock their own memory and conversation on this display. Each person uses a separate passcode.</p><div id="display-access-member-options"></div></section></div><p id="display-access-status" role="status"></p><div class="row spread"><button type="button" class="pill" id="display-access-cancel">Cancel</button><button class="pill primary" type="submit" id="display-access-save">Save access</button></div></form>';
  document.body.append(dialog);let editing=null,epoch=0;
  const badge=document.createElement('span');badge.id='display-profile-badge';badge.hidden=true;$('connection').before(badge);
  const note=document.createElement('div');note.id='guest-display-note';note.hidden=true;note.textContent='Only devices shared with this display appear below. Use their controls to make changes.';$('page-rooms').prepend(note);
  function mode(){const guest=$('display-access-mode').value==='guest';$('display-access-guest').hidden=!guest;$('display-access-description').textContent=guest?(dialog.dataset.mini==='true'?'Choose the devices available on Mini. Its room label does not share anything automatically.':'Choose the devices and read-only sources available here. No room is shared automatically.'):'Household displays can use shared memory, lists, plans and the assistant’s granted tools. Choose this only for a trusted device.';}
  $('display-access-mode').onchange=mode;
  for(const id of ['display-access-close','display-access-cancel'])$(id).onclick=()=>dialog.close();
  dialog.addEventListener('close',()=>{epoch++;editing=null;});
  document.addEventListener('echo:edit-display-access',async event=>{
    const version=++epoch,d=event.detail;editing=null;$('display-access-save').disabled=true;
    const profile=d.profile||{mode:'household',name:'Household',room:'',conversation:true,home_devices:{},calendars:[],cameras:[],presence_sensors:[]};
    const mini=d.id==='round',member=d.id.startsWith('member:');dialog.dataset.member=String(member);$('display-access-mode').querySelector('[value=household]').disabled=member;$('display-access-name').readOnly=member;$('display-access-members').hidden=member;dialog.dataset.mini=String(mini);$('display-access-voice-note').textContent=mini?'Requires guest conversation. This separate owner opt-in permits wake and Talk commands for shared devices. Turn it off to keep home actions on the physical controls only.':'Off by default. Requires guest conversation and permission for the message or the owner’s wake-word setting. Named-device and shared-room commands stay local.';$('display-access-mode').querySelector('[value=guest]').disabled=mini&&!d.firmware_ready&&profile.mode!=='guest';
    $('display-access-title').textContent=d.name;$('display-access-name').value=profile.name;$('display-access-room').value=profile.room;
    $('display-access-mode').value=profile.mode;$('display-access-conversation').checked=profile.conversation;$('display-access-home-voice').checked=profile.home_voice===true;mode();
    $('display-access-devices').replaceChildren();$('display-access-sources').replaceChildren();$('display-access-status').textContent='Loading shared devices and sources…';dialog.showModal();
    try{
      const [home,sources,accounts]=await Promise.all([api('/v1/display/home'),api('/v1/display/source-settings'),member?Promise.resolve({items:[]}):api('/v1/members')]);
      if(version!==epoch||!dialog.open)return;
      $('display-access-member-options').innerHTML=accounts.items.map(a=>`<label class="check-label"><input type="checkbox" data-profile-member="${esc(a.id)}" ${(profile.members||[]).includes(a.id)?'checked':''} ${mini&&!d.members_ready&&!(profile.members||[]).includes(a.id)?'disabled':''}>${esc(a.name)}</label>`).join('')||'<p class="tiny soft">Create an account in Settings → Personal accounts first.</p>';
      const devices=(home.devices||[]).filter(i=>['light','switch','climate','media_player','weather'].includes(i.domain));
      for(const entity of Object.keys(profile.home_devices||{}))if(!devices.some(d=>d.entity_id===entity))devices.push({entity_id:entity,name:entity,access:profile.home_devices[entity],available:false});
      $('display-access-devices').innerHTML=devices.map(i=>`<label class="access-device"><span>${esc(i.name)}<small>${esc(i.area||'No room assigned')}${i.available?'':' · unavailable'}</small></span><select data-profile-entity="${esc(i.entity_id)}"><option value="">Not shared</option><option value="read">View</option>${i.access==='control'?'<option value="control">View & control</option>':''}</select></label>`).join('')||empty('No devices are shared with Echo yet. Configure them on Devices.');
      dialog.querySelectorAll('[data-profile-entity]').forEach(el=>el.value=profile.home_devices?.[el.dataset.profileEntity]||'');
      for(const [key,label] of (mini?[]:[['calendars','Read-only calendars'],['cameras','Cameras'],['presence_sensors','Presence wake sensors']])){
        const section=document.createElement('section');section.innerHTML=`<h3>${label}</h3>`;
        for(const entity of sources.sources?.[key]||[]){const item=(sources.items||[]).find(i=>i.entity_id===entity);const row=document.createElement('label');row.className='check-label';const check=document.createElement('input');check.type='checkbox';check.dataset.profileSource=key;check.value=entity;check.checked=(profile[key]||[]).includes(entity);row.append(check,document.createTextNode(item?.name||entity));section.append(row);}
        if(section.children.length===1){const p=document.createElement('p');p.className='tiny soft';p.textContent='No sources shared in Display settings.';section.append(p);}
        $('display-access-sources').append(section);
      }
      if(mini&&!d.members_ready)$('display-access-member-options').insertAdjacentHTML('beforeend','<p class="tiny soft">Connect Mini with firmware 0.19.0 or newer to share personal accounts.</p>');
      editing={id:d.id,revision:d.profile_revision||0};$('display-access-status').textContent=mini&&!d.firmware_ready?'Connect Mini with the current firmware before first enabling Guest mode. Existing restrictions can still be reduced.':'Changes apply to this device. Switching profiles clears its conversation.';$('display-access-save').disabled=false;
    }catch(error){if(version===epoch)$('display-access-status').textContent=error.message;}
  });
  $('display-access-form').onsubmit=async event=>{
    event.preventDefault();if(!editing)return;const target=editing,version=epoch;$('display-access-save').disabled=true;
    const profile={mode:$('display-access-mode').value,name:$('display-access-name').value.trim(),room:$('display-access-room').value.trim(),conversation:$('display-access-conversation').checked,home_voice:$('display-access-home-voice').checked,home_devices:{},calendars:[],cameras:[],presence_sensors:[],members:[]};
    dialog.querySelectorAll('[data-profile-member]:checked').forEach(el=>profile.members.push(el.dataset.profileMember));
    dialog.querySelectorAll('[data-profile-entity]').forEach(el=>{if(el.value)profile.home_devices[el.dataset.profileEntity]=el.value;});
    dialog.querySelectorAll('[data-profile-source]:checked').forEach(el=>profile[el.dataset.profileSource].push(el.value));
    try{await api(target.id.startsWith('member:')?'/v1/members/'+target.id.slice(7)+'/profile':target.id==='round'?'/v1/round/profile':'/v1/displays/'+target.id+'/profile',{revision:target.revision,profile},'PUT');if(version!==epoch)return;dialog.close();pairingListAt=0;miniAt=0;await loadPairedDisplays();await loadMiniAccess();document.dispatchEvent(new Event('echo:members-changed'));toast(target.id.startsWith('member:')?'Account access saved.':'Device access saved.');}
    catch(error){if(version===epoch){$('display-access-status').textContent=error.message;$('display-access-save').disabled=false;}}
  };
  const miniCard=document.createElement('article');miniCard.className='card';miniCard.id='mini-access-card';miniCard.hidden=true;
  miniCard.innerHTML='<span class="eyebrow">ECHO MINI</span><h2>Share the round speaker</h2><p class="soft">Choose its home devices and conversation access. Guest mode keeps household memory, lists, calls and Hermes tools private. Spotify and Mini timers remain available.</p><p id="mini-access-summary" class="tiny soft" role="status"></p><button class="pill" id="mini-access-edit" disabled>Mini access</button>';
  $('page-settings').append(miniCard);let miniAt=0,miniLoading=false,miniState=null;
  async function loadMiniAccess(){
    if(miniLoading||data.session?.role!=='owner'||$('page-settings').hidden)return;
    miniLoading=true;miniAt=Date.now();
    try{miniState=await api('/v1/round/profile');$('mini-access-summary').textContent=miniState.profile.name+(miniState.profile.room?' · '+miniState.profile.room:'')+(miniState.firmware_ready?' · current firmware connected':' · current firmware connection required');$('mini-access-edit').disabled=false;}
    catch(error){miniState=null;$('mini-access-summary').textContent=error.message;$('mini-access-edit').disabled=true;}
    finally{miniLoading=false;}
  }
  $('mini-access-edit').onclick=()=>{if(miniState)document.dispatchEvent(new CustomEvent('echo:edit-display-access',{detail:{...miniState,id:'round',name:'Echo Mini access'}}));};
  extensions.push(()=>{miniCard.hidden=data.session?.role!=='owner';if(!miniCard.hidden&&Date.now()-miniAt>5000)void loadMiniAccess();});
  let accessVersion=null;
  extensions.push(()=>{
    const session=data.session;if(!session)return;
    const version=(session.receiver_id||'owner')+':'+(session.profile_revision||0);
    if(accessVersion!==null&&accessVersion!==version){document.body.style.visibility='hidden';clearVoiceReply();void closeMic();location.reload();return;}
    accessVersion=version;const profile=session.profile,guest=session.role==='display'&&profile?.mode==='guest';
    document.body.classList.toggle('guest-display',guest);document.body.classList.toggle('guest-home-voice',guest&&profile.home_voice===true&&profile.conversation);note.hidden=!guest;badge.hidden=!guest;
    if(guest){
      badge.textContent=(profile.personal?'Personal · ':'Guest · ')+profile.name+(profile.room?' · '+profile.room:'');
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
      const permission=$('allow-home');if(permission){const enabled=profile.home_voice===true&&profile.conversation;permission.closest('label').hidden=!enabled;if(!enabled)permission.checked=false;}
      note.textContent=profile.home_voice?'Only shared devices appear here. You can also ask Echo for a named device or room, such as “Turn off Guest room lights.”':'Only devices shared with this display appear below. Use their controls to make changes.';
    }else window.echoAllowedPages=null;
  });
})();

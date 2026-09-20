/* Deliberate personal sessions on shared screens. No passcodes in browser storage. */
(()=>{
  'use strict';
  const button=document.createElement('button');button.className='pill';button.id='member-button';button.hidden=true;button.textContent='Sign in';$('connection').before(button);
  const admin=document.createElement('article');admin.className='card';admin.id='members-card';admin.hidden=true;
  admin.innerHTML='<span class="eyebrow">A SPACE FOR EACH PERSON</span><h2>Personal accounts</h2><p class="soft">Separate saved memory, personality and conversations. Share an account with a Deck in Display access, then use its passcode to sign in for 15 minutes.</p><button class="pill" id="manage-members">Manage accounts</button><p class="tiny soft">Personal sessions use your configured model and public lookup. Household Hermes tools, lists and routines stay private. Mini sign-in is not available yet.</p>';
  $('page-settings').append(admin);
  const dialog=document.createElement('dialog');dialog.id='member-dialog';
  dialog.innerHTML='<div class="row spread"><div><span class="eyebrow">YOUR SPACE IN ECHO</span><h2 id="member-title"></h2></div><button class="icon-button" id="member-close" aria-label="Close personal account">×</button></div><div id="member-content"></div><p id="member-status" class="tiny soft" role="status"></p>';
  document.body.append(dialog);let epoch=0,available=[],loading=false,last=0;
  const content=$('member-content'),status=$('member-status');
  $('member-close').onclick=()=>dialog.close();
  dialog.addEventListener('close',()=>{epoch++;content.replaceChildren();status.textContent='';});
  function open(title){epoch++;content.replaceChildren();status.textContent='';$('member-title').textContent=title;if(!dialog.open)dialog.showModal();return epoch;}
  function failure(error,version){if(version===epoch&&dialog.open)status.textContent=error.message;}
  function reload(){clearVoiceReply();void closeMic();document.body.style.visibility='hidden';location.reload();}
  async function loadAvailable(){
    if(loading)return;loading=true;last=Date.now();
    try{available=(await api('/v1/members/available')).items||[];}catch{available=[];}finally{loading=false;render();}
  }
  function render(){
    admin.hidden=data.session?.role!=='owner';button.hidden=!data.session?.member&&!available.length;
    button.textContent=data.session?.member?data.session.member.name+' · Lock':'Sign in';
    if(data.session?.member){
      $('voice-privacy-note').textContent='Personal session · saved facts stay in your account · lock when finished';
      const welcome=$('chat-welcome');if(welcome)welcome.querySelector('p').textContent='Your own conversation and saved memory. Lock this screen when you finish.';
    }
  }
  extensions.push(()=>{render();if(data.session&&Date.now()-last>10000)void loadAvailable();});
  button.onclick=()=>data.session?.member?personal():signIn();
  async function signIn(){
    const version=open('Make yourself at home');await loadAvailable();if(version!==epoch)return;
    content.innerHTML='<p class="soft">Choose your account and enter its eight-digit passcode. This screen returns to its shared profile after 15 minutes.</p><form id="member-login"><label>Account<select id="member-choice" required></select></label><label>Passcode<input id="member-code" type="password" readonly autocomplete="off" aria-label="Eight-digit passcode"></label><div id="member-keypad" aria-label="Passcode keypad"></div><button class="pill primary" id="member-unlock">Unlock my account</button></form>';
    for(const account of available){const option=document.createElement('option');option.value=account.id;option.textContent=account.name;$('member-choice').append(option);}
    const code=$('member-code');let digits='';
    for(const value of ['1','2','3','4','5','6','7','8','9','Clear','0','⌫']){
      const key=document.createElement('button');key.type='button';key.textContent=value;key.className='pill';key.setAttribute('aria-label',value==='⌫'?'Delete last digit':value);
      key.onclick=()=>{digits=value==='Clear'?'':value==='⌫'?digits.slice(0,-1):digits.length<8?digits+value:digits;code.value=digits;};$('member-keypad').append(key);
    }
    // Physical keyboards and the touch keypad use the same bounded value.
    code.onkeydown=event=>{if(/^\d$/.test(event.key)){event.preventDefault();if(digits.length<8)digits+=event.key;}else if(event.key==='Backspace'){event.preventDefault();digits=digits.slice(0,-1);}code.value=digits;};
    $('member-login').onsubmit=async event=>{
      event.preventDefault();if(digits.length!==8){status.textContent='Enter all eight digits.';return;}
      const passcode=digits;digits='';code.value='';$('member-unlock').disabled=true;
      try{await api('/v1/member/session',{member:$('member-choice').value,passcode});reload();}
      catch(error){failure(error,version);if(version===epoch)$('member-unlock').disabled=false;}
    };
  }
  async function manage(){
    const version=open('Personal accounts');status.textContent='Loading…';
    try{
      const result=await api('/v1/members');if(version!==epoch)return;status.textContent='';
      content.innerHTML='<form id="member-create" class="row"><label>New account name<input id="member-name" maxlength="60" required autocomplete="off"></label><button class="pill primary">Create account</button></form><div id="member-roster"></div>';
      $('member-create').onsubmit=async event=>{event.preventDefault();try{const created=await api('/v1/members',{name:$('member-name').value});showCode(created);last=0;}catch(error){failure(error,version);}};
      for(const item of result.items){
        const row=document.createElement('article');row.className='member-row';const name=document.createElement('strong');name.textContent=item.name;row.append(name);
        for(const [label,action] of [['Access',()=>{dialog.close();document.dispatchEvent(new CustomEvent('echo:edit-display-access',{detail:{id:'member:'+item.id,name:item.name+' access',profile:item.profile,profile_revision:item.revision}}));}],['New passcode',()=>confirmChange(item,false)],['Delete',()=>confirmChange(item,true)]]){
          const control=document.createElement('button');control.className='pill';control.textContent=label;control.onclick=action;row.append(control);
        }$('member-roster').append(row);
      }
      if(!result.items.length)$('member-roster').textContent='Create the first account, then assign it to a display in Display access.';
    }catch(error){failure(error,version);}
  }
  function showCode(item){
    open('Passcode for '+item.name);content.innerHTML='<p class="soft">Save this passcode somewhere private. Echo shows it only now. The owner can replace it later.</p><output id="member-new-code"></output><p class="tiny soft">Share this account with a Deck in Settings → Paired displays → Display access. Account access controls which home devices and sources it can use.</p><button class="pill primary" id="member-code-done">I saved the passcode</button>';
    $('member-new-code').textContent=item.passcode;$('member-code-done').onclick=manage;
  }
  function confirmChange(item,remove){
    const version=open(remove?'Delete '+item.name+'?':'Replace passcode?');
    const p=document.createElement('p');p.className='soft';p.textContent=remove?'This permanently deletes the account and its saved memory. Active sessions will lock.':'The old passcode will stop working and active sessions will lock.';
    content.append(p);const yes=document.createElement('button');yes.className='pill primary';yes.textContent=remove?'Delete account and memory':'Replace passcode';content.append(yes);
    yes.onclick=async()=>{yes.disabled=true;try{const result=await api('/v1/members/'+item.id+(remove?'':'/passcode'),{revision:item.revision},remove?'DELETE':'POST');if(version!==epoch)return;last=0;if(remove)await manage();else showCode({...result,name:item.name});}catch(error){failure(error,version);yes.disabled=false;}};
  }
  async function personal(){
    const version=open(data.session.member.name+'’s space');status.textContent='Loading…';
    try{
      const [memory,prefs]=await Promise.all([api('/v1/memory'),api('/v1/member/preferences')]);if(version!==epoch)return;
      status.textContent='';content.innerHTML='<div class="row"><button class="pill primary" id="member-lock">Lock personal session</button><button class="pill" id="member-export">Export memory</button></div><p id="member-expiry" class="tiny soft"></p><form id="member-prefs"><label class="check-label"><input id="member-memory-enabled" type="checkbox">Use my saved memory in conversation</label><label>How should Echo talk with you?<textarea id="member-personality" maxlength="4000" rows="3" placeholder="Tone, preferences, things to keep in mind…"></textarea></label><button class="pill">Save preferences</button></form><h3>Saved memory</h3><form id="member-fact-form" class="row"><label>Remember something<input id="member-fact" maxlength="500" required autocomplete="off"></label><button class="pill">Save fact</button></form><div id="member-facts"></div>';
      $('member-expiry').textContent='Locks at '+new Date(data.session.member.expires_at*1000).toLocaleTimeString([],{hour:'numeric',minute:'2-digit'})+'. Anyone at this screen can use your session until you lock it.';
      $('member-memory-enabled').checked=prefs.memory_enabled;$('member-personality').value=prefs.personality;
      $('member-lock').onclick=async()=>{try{await api('/v1/member/session',{},'DELETE');reload();}catch(error){failure(error,version);}};
      $('member-prefs').onsubmit=async event=>{event.preventDefault();try{await api('/v1/member/preferences',{personality:$('member-personality').value,memory_enabled:$('member-memory-enabled').checked},'PUT');reload();}catch(error){failure(error,version);}};
      $('member-fact-form').onsubmit=async event=>{event.preventDefault();try{await api('/v1/memory',{text:$('member-fact').value});await personal();}catch(error){failure(error,version);}};
      $('member-export').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify({items:memory.items},null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='echo-personal-memory.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
      for(const fact of memory.items){const row=document.createElement('div');row.className='member-fact';const text=document.createElement('p');text.textContent=fact.text;const remove=document.createElement('button');remove.className='pill';remove.textContent='Forget';remove.onclick=async()=>{try{await api('/v1/memory/'+fact.id,{},'DELETE');await personal();}catch(error){failure(error,version);}};row.append(text,remove);$('member-facts').append(row);}
      if(!memory.items.length)$('member-facts').textContent='Nothing saved yet. You can add a fact here or ask Echo to remember it.';
    }catch(error){failure(error,version);}
  }
  setInterval(()=>{if(data.session?.member?.expires_at*1000<=Date.now())reload();},1000);
  $('manage-members').onclick=manage;
  document.addEventListener('echo:members-changed',()=>{last=0;});
})();

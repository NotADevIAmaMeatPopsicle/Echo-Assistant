/* Private Google calendars. Flow proof and account data stay only in memory. */
(()=>{
  const base='/v1/member/calendar/google';
  const button=document.createElement('button');button.id='member-google-button';button.className='pill';button.textContent='My Google calendars';button.hidden=true;
  ($('member-button')||$('connection')).after(button);
  const dialog=document.createElement('dialog');dialog.id='member-google-dialog';
  dialog.innerHTML='<div class="row spread"><div><span class="eyebrow">YOUR PRIVATE CALENDARS</span><h2>My Google calendars</h2></div><button type="button" class="icon-button" id="member-google-close" aria-label="Close private Google calendars">×</button></div><p class="soft">Connect your own Google account for read-only access in your personal session. Choose which calendars appear in My day. These connections are not shared with the household or other people.</p><div id="member-google-content"></div><p id="member-google-status" class="tiny soft" role="status"></p>';
  document.body.append(dialog);
  const client=[...crypto.getRandomValues(new Uint8Array(32))].map(value=>value.toString(16).padStart(2,'0')).join('');
  let epoch=0,identity='',state=null,flow=null,busy=false,polling=false;
  function stamp(){const session=data.session;return session?.profile?.personal&&session.member&&session.member.expires_at*1000>Date.now()?`${session.member.id}:${session.profile_revision}:${session.member.expires_at}`:'';}
  function current(version){return version===epoch&&identity&&identity===stamp()&&dialog.open;}
  function status(message){$('member-google-status').textContent=message;}
  function invalidate(){epoch++;identity='';state=null;flow=null;busy=false;$('member-google-content').replaceChildren();status('');}
  function reset(){invalidate();if(dialog.open)dialog.close();}
  function refreshAgenda(){delete data.agenda;delete received.agenda;delete data.calendarAgenda;delete received.calendarAgenda;delete data.sources;delete received.sources;refresh();}
  async function request(path,body,method,version=epoch){
    if(!current(version))throw Error('Personal session changed. Open your calendars again.');
    const result=await api(base+path,body,method);
    if(!current(version))throw Error('Personal session changed. Open your calendars again.');
    return result;
  }
  function flowView(statusValue){
    if(!$('member-google-flow'))return;
    $('member-google-flow').hidden=!flow;
    if(!flow)return;
    const words={waiting:'Open Google sign-in, choose your own account, then return to this Echo tab.',exchanging:'Receiving Google’s response…',approved:'Google approved read access. Finish connecting in this personal session.',declined:'Google sign-in was declined or cancelled. Cancel here to start again.',failed:'Google sign-in failed or required access was not granted. Cancel here to try again.'};
    $('member-google-flow-status').textContent=words[statusValue]||'Checking Google sign-in…';
    $('member-google-finish').hidden=statusValue!=='approved';$('member-google-signin').hidden=statusValue!=='waiting';
  }
  function render(){
    if(!state||!identity||identity!==stamp())return;
    $('member-google-content').innerHTML=`<div id="member-google-accounts">${state.accounts.map(account=>`<article class="member-google-account"><h3>${esc(account.label)}</h3><p class="tiny soft">${Number(account.calendar_count)} calendars found · private read-only connection</p><div class="row"><button type="button" class="pill" data-private-sync="${esc(account.id)}">Refresh calendar list</button><button type="button" class="pill" data-private-disconnect="${esc(account.id)}">Disconnect</button></div></article>`).join('')}</div><form id="member-google-connect"><label>Connection label<input id="member-google-label" maxlength="60" value="My Google calendar" autocomplete="off" required></label><button class="pill primary" id="member-google-begin">Connect my account</button></form><div id="member-google-flow" hidden><h3>Continue with Google</h3><p id="member-google-flow-status" class="soft"></p><div class="row"><a id="member-google-signin" class="pill primary" target="_blank" rel="noopener noreferrer">Open Google sign-in</a><button type="button" class="pill primary" id="member-google-finish" hidden>Finish connecting</button><button type="button" class="pill" id="member-google-cancel">Cancel sign-in</button></div></div><form id="member-google-selection"><h3>Show in my personal agenda</h3><div id="member-google-calendars">${state.calendars.map(calendar=>`<label class="member-google-calendar"><input type="checkbox" value="${esc(calendar.entity_id)}" ${calendar.selected?'checked':''}><span>${esc(calendar.name)}<small>${esc(calendar.account_label)} · ${esc(calendar.timezone)}</small></span></label>`).join('')||'<p class="soft">No private calendars found yet. Connect an account, then refresh its calendar list.</p>'}</div><button class="pill primary" id="member-google-save">Save my selection</button></form><p class="tiny soft">Explicitly shared household calendars stay under your existing access settings. This connection adds no editing or invitation permission. Lock your personal session when finished.</p>`;
    $('member-google-begin').disabled=!state.enabled||!state.configured||state.needs_reconnect;
    $('member-google-save').disabled=!state.calendars.length||state.needs_reconnect;
    status(!state.enabled?'Google connections are disabled on this host.':!state.configured?'The owner must configure Google OAuth in the owner workspace first.':state.needs_reconnect?'The owner changed Google setup. Disconnect the old private connection, then connect again.':'Select only the private calendars you want in your agenda.');
    $('member-google-connect').onsubmit=begin;
    $('member-google-selection').onsubmit=select;
    $('member-google-cancel').onclick=cancel;
    $('member-google-finish').onclick=finish;
    $('member-google-accounts').onclick=accountAction;
  }
  async function load(version=epoch){const result=await request('',undefined,undefined,version);if(current(version)){state=result;render();}}
  async function open(){
    const active=stamp();if(!active)return;
    reset();identity=active;const version=epoch;dialog.showModal();status('Loading your private connections…');
    try{await load(version);}catch(error){if(current(version))status(error.message);}
  }
  async function begin(event){
    event.preventDefault();if(busy||flow||!current(epoch))return;
    if(data.health?.display_demo){status('This preview does not sign in to Google.');return;}
    const version=epoch;busy=true;$('member-google-begin').disabled=true;
    try{const result=await request('/flows',{label:$('member-google-label').value,client},undefined,version);const url=new URL(result.url);
      if(url.origin!=='https://accounts.google.com'||url.pathname!=='/o/oauth2/v2/auth')throw Error('Unexpected Google sign-in address.');
      flow=result;$('member-google-signin').href=result.url;flowView('waiting');
    }catch(error){if(current(version)){status(error.message);$('member-google-begin').disabled=false;}}finally{if(current(version))busy=false;}
  }
  async function cancel(){
    const old=flow,version=epoch;flow=null;flowView();if($('member-google-signin'))$('member-google-signin').removeAttribute('href');
    if(old)try{await request('/flows/'+old.id,{client},'DELETE',version);}catch(error){if(current(version))status(error.message);}
    if(current(version))$('member-google-begin').disabled=!state?.configured||!state?.enabled||state?.needs_reconnect;
  }
  async function finish(){
    if(!flow||busy)return;const old=flow,version=epoch;busy=true;$('member-google-finish').disabled=true;
    try{const account=await request('/flows/'+old.id+'/finish',{client},undefined,version);flow=null;
      try{await request('/accounts/'+account.id+'/sync',{},undefined,version);await load(version);status('Connected privately. Choose calendars and save your selection.');}
      catch(error){if(current(version)){await load(version);status('Connected, but the calendar list could not load. Use Refresh calendar list.');}}
      if(current(version))refreshAgenda();
    }catch(error){if(current(version))status(error.message);}finally{if(current(version)){busy=false;if($('member-google-finish'))$('member-google-finish').disabled=false;}}
  }
  async function select(event){
    event.preventDefault();if(busy||flow)return;const version=epoch;busy=true;$('member-google-save').disabled=true;
    const calendars=[...$('member-google-calendars').querySelectorAll('input:checked')].map(input=>input.value);
    try{await request('/selection',{revision:state.revision,calendars},'PUT',version);await load(version);status('Your private calendar selection was saved.');refreshAgenda();}
    catch(error){if(current(version))status(error.message);}finally{if(current(version)){busy=false;$('member-google-save').disabled=!state?.calendars.length;}}
  }
  async function accountAction(event){
    const control=event.target.closest('button'),id=control?.dataset.privateSync||control?.dataset.privateDisconnect;if(!id||busy||flow)return;
    const disconnect=!!control.dataset.privateDisconnect;
    if(disconnect&&!window.confirm('Disconnect this private Google account? Its calendars will leave your personal agenda.'))return;
    const version=epoch;busy=true;control.disabled=true;
    try{await request('/accounts/'+id+(disconnect?'':'/sync'),{},disconnect?'DELETE':undefined,version);await load(version);refreshAgenda();}
    catch(error){if(current(version))status(error.message);}finally{if(current(version))busy=false;}
  }
  async function poll(){
    if(!flow||polling||document.hidden||!current(epoch))return;const old=flow,version=epoch;polling=true;
    try{const result=await request('/flows/'+old.id+'?client='+client,undefined,undefined,version);if(current(version)&&flow===old)flowView(result.status);}
    catch(error){if(current(version)&&flow===old){flow=null;flowView();status(error.message);$('member-google-signin').removeAttribute('href');$('member-google-begin').disabled=false;}}
    finally{polling=false;}
  }
  function observe(){const active=stamp();button.hidden=!active;if(identity&&identity!==active)reset();}
  $('member-google-close').onclick=()=>dialog.close();
  dialog.addEventListener('close',()=>{const old=flow,active=identity;invalidate();if(old&&active===stamp())void api(base+'/flows/'+old.id,{client},'DELETE').catch(()=>{});});
  button.onclick=()=>void open();extensions.push(observe);
  setInterval(observe,500);setInterval(()=>void poll(),3000);
  window.EchoMemberGoogle={open};
})();

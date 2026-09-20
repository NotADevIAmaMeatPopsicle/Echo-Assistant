/* Owner-authorized Google account connection. Tokens never enter this page. */
'use strict';
(()=>{
  const card=document.createElement('article');card.className='card google-calendar-card';card.id='google-calendar-card';card.hidden=true;
  card.innerHTML=`<span class="eyebrow">YOUR CALENDARS</span><h2>Connect Google Calendar.</h2><p class="soft">Bring your calendars into My day and Echo’s agenda replies. You choose which calendars and displays can see them.</p><button class="pill" id="google-load" type="button">Manage Google calendars</button><div id="google-panel" hidden><p class="soft" id="google-status" role="status"></p><details id="google-setup"><summary>Google OAuth setup</summary><p class="tiny soft">Create a web OAuth client in Google Cloud, enable the Calendar API, and register the exact callback URL below. These settings belong to this Echo installation.</p><form id="google-config"><label>Client ID<input id="google-client-id" autocomplete="off" spellcheck="false" type="text" required></label><label>Client secret<input id="google-client-secret" autocomplete="new-password" type="password" placeholder="Leave blank to keep saved"></label><label>Authorized redirect URI<input id="google-redirect" autocomplete="off" spellcheck="false" type="url" required></label><button class="pill primary" type="submit">Save Google setup</button></form></details><div id="google-accounts"></div><form id="google-connect"><label>Label for this connection<input id="google-label" type="text" maxlength="60" value="Google calendar" required></label><button class="pill primary" id="google-begin" type="submit">Connect an account</button></form><div id="google-flow" hidden><h3>Continue with Google</h3><p id="google-flow-status" class="soft" role="status"></p><div class="row"><a class="pill primary" id="google-signin" target="_blank" rel="noopener noreferrer">Open Google sign-in</a><button class="pill primary" id="google-finish" type="button" hidden>Finish connecting</button><button class="pill" id="google-cancel" type="button">Cancel</button></div></div><p class="tiny soft">This connection currently requests read-only Calendar access. It does not send invitations or edit Google events. Tokens stay encrypted on the host. After connecting, use Calendars & cameras → Load sources to select what is shared.</p></div>`;
  sourceCard.before(card);
  const client=[...crypto.getRandomValues(new Uint8Array(32))].map(n=>n.toString(16).padStart(2,'0')).join('');
  let state=null,flow=null,polling=false,saving=false;
  function renderAccounts(){
    $('google-accounts').innerHTML=(state.accounts||[]).map(a=>`<div class="google-account"><h3>${esc(a.label)}</h3><p class="tiny soft">${a.calendar_count} calendars found · sharing is selected separately</p><div class="row"><button class="pill" type="button" data-google-sync="${esc(a.id)}">Refresh calendar list</button><button class="pill" type="button" data-google-disconnect="${esc(a.id)}">Disconnect</button></div></div>`).join('');
  }
  async function load(){
    state=await api('/v1/calendar/google');$('google-panel').hidden=false;$('google-client-id').value=state.client_id;$('google-redirect').value=state.redirect_uri||location.origin+'/v1/calendar/google/callback';$('google-client-secret').value='';
    $('google-setup').open=!state.secret_saved;$('google-begin').disabled=!state.secret_saved||!state.enabled||!!flow;
    $('google-status').textContent=!state.enabled?'Account connections are disabled on this host.':state.secret_saved?'Google setup is saved. Connect an account, then choose its shared calendars.':'Configure a Google web OAuth client to get started.';renderAccounts();
  }
  function clearFlow(){flow=null;$('google-flow').hidden=true;$('google-signin').removeAttribute('href');$('google-finish').hidden=true;$('google-begin').disabled=!state?.secret_saved||!state?.enabled;}
  function showFlow(status){
    const text={waiting:'Open Google sign-in, choose the account and approve Calendar access. Then return here.',exchanging:'Receiving Google’s response…',approved:'Google approved access. Finish connecting here to save it to this Echo installation.',declined:'Sign-in was cancelled or permission was declined. You can cancel here and try again.',failed:'The required access was not granted or the Google connection failed. Cancel here and start again.'};
    $('google-flow-status').textContent=text[status]||'Checking sign-in…';$('google-finish').hidden=status!=='approved';$('google-signin').hidden=status!=='waiting';
  }
  $('google-load').onclick=()=>void action(load,'Google calendar settings loaded.');
  $('google-config').onsubmit=async e=>{
    e.preventDefault();if(!state||saving)return;saving=true;const button=e.submitter;button.disabled=true;
    try{await api('/v1/calendar/google',{revision:state.revision,client_id:$('google-client-id').value.trim(),client_secret:$('google-client-secret').value,redirect_uri:$('google-redirect').value.trim()},'PUT');clearFlow();await load();toast('Google setup saved.');}
    catch(error){$('google-status').textContent=error.message;}finally{saving=false;button.disabled=false;}
  };
  $('google-connect').onsubmit=async e=>{
    e.preventDefault();if(flow||saving)return;
    if(data.health?.display_demo){toast('This preview does not sign in to Google.');return;}
    saving=true;$('google-begin').disabled=true;
    try{
      const result=await api('/v1/calendar/google/flows',{label:$('google-label').value,client});const url=new URL(result.url);
      if(url.origin!=='https://accounts.google.com'||url.pathname!=='/o/oauth2/v2/auth')throw Error('Unexpected Google sign-in address.');
      flow=result;$('google-flow').hidden=false;$('google-signin').href=result.url;showFlow('waiting');
    }catch(error){$('google-status').textContent=error.message;$('google-begin').disabled=false;}finally{saving=false;}
  };
  $('google-cancel').onclick=async()=>{const old=flow;clearFlow();if(old)try{await api('/v1/calendar/google/flows/'+old.id,{client},'DELETE');}catch{};};
  $('google-finish').onclick=async()=>{
    if(!flow||saving)return;saving=true;$('google-finish').disabled=true;const old=flow;
    try{const account=await api('/v1/calendar/google/flows/'+old.id+'/finish',{client});clearFlow();
      try{await api('/v1/calendar/google/accounts/'+account.id+'/sync',{});await load();$('google-status').textContent='Connected. Now select calendars under Calendars & cameras → Load sources.';}
      catch(error){await load();$('google-status').textContent='Connected, but the calendar list could not load. Use Refresh calendar list to retry.';}
    }catch(error){$('google-flow-status').textContent=error.message;}finally{saving=false;$('google-finish').disabled=false;}
  };
  $('google-accounts').onclick=async e=>{
    const button=e.target.closest('button'),id=button?.dataset.googleSync||button?.dataset.googleDisconnect;if(!id||saving)return;
    if(button.dataset.googleDisconnect&&!window.confirm('Disconnect this Google account from Echo? Its calendars will stop updating here. You can also revoke the app in Google Account permissions.'))return;
    saving=true;button.disabled=true;
    try{await api('/v1/calendar/google/accounts/'+id+(button.dataset.googleSync?'/sync':''),{},button.dataset.googleSync?'POST':'DELETE');await load();delete data.agenda;delete received.agenda;refresh();}
    catch(error){$('google-status').textContent=error.message;}finally{saving=false;button.disabled=false;}
  };
  async function poll(){
    if(!flow||polling||document.hidden)return;polling=true;const old=flow;
    try{const result=await api('/v1/calendar/google/flows/'+old.id+'?client='+client);if(flow===old)showFlow(result.status);}
    catch(error){if(flow===old){clearFlow();$('google-status').textContent=error.message;}}finally{polling=false;}
  }
  setInterval(()=>void poll(),3000);
  extensions.push(()=>{card.hidden=data.session?.role!=='owner';if(card.hidden){clearFlow();$('google-client-secret').value='';}});
})();

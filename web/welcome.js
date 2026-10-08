/* First-visit owner setup. Never persist a passcode or Google credential in the browser. */
(()=>{
  'use strict';
  const $=id=>document.getElementById(id);
  const sections=['account','google','devices','done'];
  let accountName='';
  async function api(path,method='GET',body){
    const response=await fetch(path,{method,credentials:'same-origin',headers:body?{'Content-Type':'application/json','X-Echo-Request':'1'}:{'X-Echo-Request':'1'},body:body?JSON.stringify(body):undefined});
    let data={};try{data=await response.json();}catch{}
    if(!response.ok)throw new Error(data.detail || (response.status===401?'Your owner session ended. Open Echo from its launcher again.':'Echo could not complete this step.'));
    return data;
  }
  function show(step){
    for(const name of sections){$("welcome-"+name).hidden=name!==step;const marker=$("welcome-progress-"+name);marker.removeAttribute('aria-current');if(name===step)marker.setAttribute('aria-current','step');}
    $('welcome-status').hidden=true;
    window.scrollTo(0,0);
  }
  function finish(){
    try{localStorage.removeItem('echo-welcome-pending');}catch{}
    $('welcome-summary').textContent=accountName?accountName+'’s Personal account is ready.':'A Personal account is ready.';
    show('done');
  }
  async function start(){
    try{
      const roster=await api('/v1/members');
      if(roster.items.length)show('google');
      else show('account');
    }catch(error){$('welcome-status').textContent=error.message;}
  }
  $('welcome-account-form').addEventListener('submit',async event=>{
    event.preventDefault();const button=event.submitter;button.disabled=true;$('welcome-status').hidden=false;$('welcome-status').textContent='Creating your account…';
    try{
      const created=await api('/v1/members','POST',{name:$('welcome-name').value.trim()});
      accountName=created.name;try{localStorage.setItem('echo-welcome-pending','1');}catch{}
      $('welcome-code').textContent=created.passcode;$('welcome-account-form').hidden=true;$('welcome-passcode').hidden=false;$('welcome-status').hidden=true;
    }catch(error){$('welcome-status').textContent=error.message;button.disabled=false;}
  });
  $('welcome-code-saved').addEventListener('change',event=>{$('welcome-account-next').disabled=!event.target.checked;});
  $('welcome-account-next').addEventListener('click',()=>{$('welcome-code').textContent='';show('google');});
  $('welcome-google-next').addEventListener('click',()=>show('devices'));
  $('welcome-google-skip').addEventListener('click',()=>show('devices'));
  $('welcome-devices-next').addEventListener('click',finish);
  $('welcome-devices-skip').addEventListener('click',finish);
  start();
})();

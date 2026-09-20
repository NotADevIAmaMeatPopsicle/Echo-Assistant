'use strict';
endpoints.session='/v1/display/session';
const pairingCard=document.createElement('article'); pairingCard.className='card pairing-card'; pairingCard.hidden=true;
pairingCard.innerHTML='<span class="eyebrow">YOUR DISPLAYS</span><h2>One Echo. More places to use it.</h2><div id="paired-displays"></div><form id="pairing-form" class="inline-form"><input id="pairing-name" maxlength="60" required placeholder="Kitchen display" aria-label="New display name"><button class="pill primary" type="submit" data-requires="session">Create pairing code</button></form><div id="pairing-code-panel" hidden><p class="soft">Enter this one-use code in the Pi setup prompt. It expires in five minutes.</p><output id="pairing-code"></output><button class="pill" id="copy-pairing" type="button">Copy code</button></div><p class="tiny soft">Displays can use household features. Provider keys and access settings remain in the owner workspace. Revoke a display here to disconnect it.</p>';
$('page-settings').append(pairingCard);
let pairExpiry=0, pairingListLoading=false, pairingListAt=0,pairedEntries=[];
async function loadPairedDisplays() {
  if (pairingListLoading || data.session?.role!=='owner' || $('page-settings').hidden) return;
  pairingListLoading=true;
  try {
    const result=await api('/v1/displays'); pairingListAt=Date.now();pairedEntries=result.items;
    $('paired-displays').innerHTML=result.items.length ? result.items.map(d=>`<div class="schedule-item row spread"><div><strong>${esc(d.name)}</strong><p class="tiny soft">${esc(d.profile?.name||'Household')}${d.profile?.room?' · '+esc(d.profile.room):''}<br>${d.last_seen ? 'Last seen '+esc(new Date(d.last_seen*1000).toLocaleString()) : 'No connection in this host session'}</p></div><div class="row"><button class="pill" data-profile-display="${d.id}">Access</button><button class="pill" data-revoke-display="${d.id}">Revoke</button></div></div>`).join('') : empty('No paired displays yet.');
  } catch(error) { $('paired-displays').textContent=error.message; }
  finally { pairingListLoading=false; }
}
extensions.push(()=>{
  const owner=data.session?.role==='owner'; pairingCard.hidden=!owner;
  $('pairing-form').querySelector('button').dataset.unavailable=String(!!data.health?.display_demo);
  $('pairing-form').querySelector('button').title=data.health?.display_demo ? 'Pair displays from the live owner workspace. This demo has no credentials.' : '';
  if (data.session?.role==='display') document.querySelectorAll('a[href="/settings"],a[href="/devices"],a[href="/routines"]').forEach(link=>{link.hidden=true;});
  if (owner && Date.now()-pairingListAt>5000) loadPairedDisplays();
});
$('pairing-form').onsubmit=event=>{event.preventDefault(); if (data.session?.role!=='owner') return; action(async()=>{
  const result=await api('/v1/displays/pairing',{name:$('pairing-name').value.trim()});
  $('pairing-code').textContent=result.code; pairExpiry=result.expires_at*1000; $('pairing-code-panel').hidden=false;
},'Pairing code ready.');};
$('copy-pairing').onclick=async()=>{try{await navigator.clipboard.writeText($('pairing-code').textContent);toast('Pairing code copied.');}catch{toast('Select and copy the code shown here.');}};
pairingCard.addEventListener('click',event=>{const button=event.target.closest('[data-revoke-display]'); if (button && data.session?.role==='owner') action(async()=>{await api('/v1/displays/'+button.dataset.revokeDisplay,{},'DELETE');pairingListAt=0;await loadPairedDisplays();},'Display access revoked.');});
pairingCard.addEventListener('click',event=>{const button=event.target.closest('[data-profile-display]');if(button&&data.session?.role==='owner'){const display=pairedEntries.find(d=>d.id===button.dataset.profileDisplay);if(display)document.dispatchEvent(new CustomEvent('echo:edit-display-access',{detail:display}));}});
setInterval(()=>{if(pairExpiry && Date.now()>=pairExpiry){$('pairing-code').textContent='';$('pairing-code-panel').hidden=true;pairExpiry=0;}},1000);

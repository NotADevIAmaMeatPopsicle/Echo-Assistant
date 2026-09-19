/* Room audio is opt-in per receiver. No messages, claims or audio in browser storage. */
'use strict';
titles.audio='A little closer, room to room.';
endpoints.audioRooms='/v1/audio/rooms';endpoints.audioMessages='/v1/audio/messages';
pageEndpoints.audioMessages='audio';
const roomPage=document.createElement('section');roomPage.id='page-audio';roomPage.className='page';roomPage.hidden=true;
roomPage.innerHTML=`<div class="row spread section-head"><p class="soft">Send a spoken message to the rooms you choose.</p><button class="pill" data-page="planner">Back to Planner</button></div><div class="two-columns room-audio-grid"><article class="card"><span class="eyebrow">ROOM ANNOUNCEMENT</span><h2>Let them know.</h2><form id="announcement-form"><fieldset id="announcement-draft" aria-label="Room announcement"><label>Title<input id="announcement-title" maxlength="80" value="A message for home" required></label><label>Message<textarea id="announcement-text" maxlength="400" rows="3" required placeholder="Dinner’s ready. Come on down."></textarea></label><div id="announcement-targets" role="group" aria-label="Recipients"></div></fieldset><p class="tiny soft">Quiet or offline receivers wait up to five minutes. Messages expire after that. Delivery history is kept for 24 hours.</p><div class="row wrap"><button class="pill primary" id="announcement-send" type="submit" data-requires="audioRooms">Send announcement</button><button class="text-button" id="announcement-new" type="button">New message</button></div><p class="tiny soft" id="announcement-result" role="status"></p></form></article><article class="card"><span class="eyebrow">DELIVERY HISTORY</span><h2>On its way.</h2><div id="announcement-history"></div><p class="tiny soft">“Played” is the receiver’s report. An unknown result is never automatically replayed.</p></article></div>`;
document.querySelector('main').append(roomPage);
const roomLink=document.createElement('div');roomLink.className='row spread section-head';roomLink.innerHTML='<p class="soft">A message for another room?</p><button class="pill" data-page="audio">Room audio ↗</button>';$('page-planner').prepend(roomLink);
const receiverCard=document.createElement('article');receiverCard.className='card pairing-card';receiverCard.hidden=true;
receiverCard.innerHTML='<span class="eyebrow">SOUND ON THIS DISPLAY</span><h2>Hear room announcements.</h2><p class="soft tiny">Enable this after the owner assigns this display to a room. Each new browser session starts with receiving off.</p><div class="row wrap"><button class="pill primary" id="announcement-listen">Enable announcements here</button><button class="pill" data-page="audio">Room audio ↗</button></div><label>Announcement volume <output id="announcement-volume-label">2%</output><input id="announcement-volume" type="range" min="1" max="30" value="2"></label><p class="tiny soft" id="announcement-receiver-status" role="status">Receiving is off.</p>';
$('page-settings').append(receiverCard);
const roomSettings=document.createElement('article');roomSettings.className='card pairing-card';roomSettings.hidden=true;
roomSettings.innerHTML='<span class="eyebrow">ROOM RECEIVERS</span><h2>Give every Echo a place.</h2><p class="tiny soft">Only enabled receivers can be selected. A display also needs receiving enabled on its own Settings page. Announcements respect the quiet hours in Planner.</p><form id="audio-room-form"><div id="audio-room-settings"></div><button class="pill primary" type="submit" data-requires="audioRooms">Save room assignments</button></form><button class="text-button" data-page="audio">Open room audio ↗</button>';
$('page-settings').append(roomSettings);
let roomSignature='',roomDirty=false,roomRevision=0,targetSignature='',messageDraft=null,messageSent=false;
const deliveryLabels={queued:'Waiting',claimed:'Delivering',played:'Played · receiver report',cancelled:'Cancelled',failed:'Failed',unknown:'Unknown · not replayed',expired:'Expired'};
function renderRoomAudio(){
  const state=data.audioRooms,items=state?.items||[],owner=data.session?.role==='owner';
  roomSettings.hidden=!owner;receiverCard.hidden=!data.session?.receiver_id;
  const signature=JSON.stringify([state?.revision,items]);
  if(owner&&state&&!roomDirty&&signature!==roomSignature){
    roomSignature=signature;roomRevision=state.revision;
    $('audio-room-settings').innerHTML=items.map(i=>`<div class="audio-room-setting" data-endpoint="${esc(i.id)}"><div><strong>${esc(i.name)}</strong><small class="soft">${esc(human(i.status))}</small></div><label>Room<input data-audio-room maxlength="60" value="${esc(i.room)}" placeholder="Kitchen"></label><label class="check-label"><input type="checkbox" data-audio-enabled ${i.enabled?'checked':''}>Enabled</label></div>`).join('')||empty('Pair a display first.');
  }
  const targets=items.filter(i=>i.enabled),targetState=JSON.stringify(targets);
  if(!messageDraft&&targetState!==targetSignature){
    const checked=new Set([...$('announcement-targets').querySelectorAll(':checked')].map(i=>i.value));targetSignature=targetState;
    $('announcement-targets').innerHTML=targets.map(i=>`<label class="audio-target"><input type="checkbox" value="${esc(i.id)}" ${checked.has(i.id)?'checked':''}><span><strong>${esc(i.room)}</strong><small>${esc(i.name)} · ${esc(human(i.status))}</small></span></label>`).join('')||empty('No rooms enabled yet. Assign receivers in Settings.');
  }
  $('announcement-send').dataset.unavailable=String(messageSent||!targets.length);
  const messages=data.audioMessages?.items||[];
  $('announcement-history').innerHTML=messages.map(m=>`<div class="audio-delivery"><strong>${esc(m.title)}</strong><p>${esc(m.message)}</p><ul>${m.deliveries.map(d=>`<li>${esc(d.room)} <span>${esc(deliveryLabels[d.status]||d.status)}</span></li>`).join('')}</ul>${m.deliveries.some(d=>['queued','claimed'].includes(d.status))?`<button class="text-button" data-announcement-cancel="${esc(m.id)}" data-requires="audioMessages">Cancel delivery</button>`:''}</div>`).join('')||empty(fresh('audioMessages')?'No announcements yet.':'Open this page while connected to view delivery history.');
}
extensions.push(renderRoomAudio);
$('audio-room-form').oninput=()=>roomDirty=true;
$('audio-room-form').onsubmit=event=>{event.preventDefault();action(async()=>{
  const endpoints=[...$('audio-room-settings').children].filter(row=>row.dataset.endpoint).map(row=>({id:row.dataset.endpoint,room:row.querySelector('[data-audio-room]').value.trim(),enabled:row.querySelector('[data-audio-enabled]').checked}));
  if(endpoints.some(i=>i.enabled&&!i.room))throw Error('Give each enabled receiver a room name.');
  await api('/v1/audio/rooms',{endpoints:endpoints.filter(i=>i.room),revision:roomRevision},'PUT');roomDirty=false;roomSignature='';
},'Room assignments saved.');};
$('announcement-new').onclick=()=>{messageDraft=null;messageSent=false;targetSignature='';$('announcement-draft').disabled=false;$('announcement-text').value='';$('announcement-result').textContent='';$('announcement-send').textContent='Send announcement';renderRoomAudio();guardButtons();};
$('announcement-form').onsubmit=event=>{event.preventDefault();if(messageSent||!fresh('audioRooms'))return;action(async()=>{
  if(!messageDraft){
    const targets=[...$('announcement-targets').querySelectorAll(':checked')].map(i=>i.value);
    if(!targets.length)throw Error('Select at least one room.');
    messageDraft={id:crypto.randomUUID().replaceAll('-',''),title:$('announcement-title').value.trim(),message:$('announcement-text').value.trim(),targets,revision:data.audioRooms.revision,issued_at:Date.now()/1000};
    $('announcement-draft').disabled=true;
  }
  try{await api('/v1/audio/messages',messageDraft);messageSent=true;$('announcement-result').textContent='Message queued. Delivery results appear alongside it.';$('announcement-send').textContent='Sent';}
  catch(error){$('announcement-result').textContent=error.message+' Retry keeps the same request, so it cannot duplicate an accepted message.';$('announcement-send').textContent='Retry same message';throw error;}
},'Announcement queued for the selected rooms.');};
document.addEventListener('click',event=>{const button=event.target.closest('[data-announcement-cancel]');if(button)action(()=>api('/v1/audio/messages/'+button.dataset.announcementCancel,{},'DELETE'),'Cancellation requested.');});

const audioClient=crypto.randomUUID().replaceAll('-','');
let announceContext=null,announceGain=null,announceSource=null,announceCurrent=null,announceEnabled=false,announcePolling=false,announceEpoch=0,announceController=null;
function audioBusy(){return displayCaptureBusy||!!chatAbort||!player.paused;}
function receivingReady(){return announceEnabled&&announceContext?.state==='running'&&!document.hidden;}
function receiverStatus(text){$('announcement-receiver-status').textContent=text;}
async function announcementReceipt(current,status){if(!current?.claim)return;try{await api('/v1/audio/inbox/'+current.id+'/receipt',{claim:current.claim,status});}catch{receiverStatus('Playback stopped. Its delivery report could not be confirmed.');}}
function stopAnnouncement(status='cancelled'){
  announceEpoch++;announceController?.abort();announceController=null;
  if(announceSource){announceSource.onended=null;try{announceSource.stop();}catch{}announceSource=null;}
  const current=announceCurrent;announceCurrent=null;void announcementReceipt(current,status);
}
async function receiveAnnouncement(item){
  const epoch=++announceEpoch,controller=new AbortController();announceController=controller;
  const current={id:item.id,claim:null};announceCurrent=current;receiverStatus('Preparing '+item.title+'…');
  try{
    const claim=await api('/v1/audio/inbox/'+item.id+'/claim',{client:audioClient},'POST',AbortSignal.any([controller.signal,AbortSignal.timeout(10000)]));current.claim=claim.claim;
    if(epoch!==announceEpoch){await announcementReceipt(current,'cancelled');return;}
    const response=await fetch('/v1/audio/inbox/'+item.id+'/audio',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Echo-Request':'1'},body:JSON.stringify({claim:current.claim}),signal:AbortSignal.any([controller.signal,AbortSignal.timeout(100000)]),cache:'no-store'});
    if(!response.ok)throw Error('Announcement audio unavailable.');
    const bytes=await response.arrayBuffer();if(bytes.byteLength>5760100)throw Error('Announcement audio exceeded its limit.');
    const decoded=await announceContext.decodeAudioData(bytes);
    const inbox=await api('/v1/audio/inbox?client='+audioClient);
    if(epoch!==announceEpoch)return;
    if(!receivingReady()||audioBusy()||!inbox.ready||!inbox.active.some(i=>i.id===item.id&&i.status==='claimed')){stopAnnouncement();return;}
    announceSource=announceContext.createBufferSource();announceSource.buffer=decoded;announceSource.connect(announceGain);
    announceSource.onended=()=>{if(epoch!==announceEpoch)return;announceSource=null;announceCurrent=null;announceController=null;receiverStatus('Announcement played. Listening for the next message.');void announcementReceipt(current,'played');};
    announceSource.start();receiverStatus('Playing '+item.title+'.');
  }catch(error){if(epoch===announceEpoch){stopAnnouncement('failed');receiverStatus('Announcement could not play. It will not automatically replay.');}}
}
async function pollAnnouncements(){
  if(announcePolling||!data.session?.receiver_id||!fresh('session'))return;
  announcePolling=true;
  try{
    const inbox=await api('/v1/audio/receiver',{client:audioClient,ready:receivingReady(),busy:audioBusy()});
    if(announceCurrent&&(!receivingReady()||audioBusy()||!inbox.enabled||['quiet_hours','another_session'].includes(inbox.status)||inbox.active.some(i=>i.id===announceCurrent.id&&i.status!=='claimed')))stopAnnouncement();
    if(!announceCurrent){
      receiverStatus(!announceEnabled?'Receiving is off.':!receivingReady()?'Tap Enable to allow audio again.':!inbox.enabled?'The owner needs to enable this receiver in room assignments.':inbox.status==='quiet_hours'?'Quiet hours · messages wait until they expire.':inbox.status==='another_session'?'Another tab is receiving for this display.':inbox.ready?'Ready for announcements at '+$('announcement-volume').value+'% volume.':'Waiting until this display is free.');
      if(inbox.ready&&receivingReady()&&!audioBusy()&&inbox.items.length)void receiveAnnouncement(inbox.items[0]);
    }
  }catch{if(announceCurrent)stopAnnouncement();receiverStatus('Connection unavailable. Receiving is paused.');}
  finally{announcePolling=false;}
}
$('announcement-listen').onclick=async()=>{
  if(announceEnabled&&announceContext?.state==='running'){announceEnabled=false;stopAnnouncement();$('announcement-listen').textContent='Enable announcements here';}
  else try{
    announceContext ||= new AudioContext();announceGain ||= announceContext.createGain();announceGain.gain.value=Number($('announcement-volume').value)/100;announceGain.connect(announceContext.destination);
    await announceContext.resume();announceEnabled=true;$('announcement-listen').textContent='Stop receiving';
  }catch{receiverStatus('This browser could not enable audio.');return;}
  void pollAnnouncements();
};
$('announcement-volume').oninput=()=>{$('announcement-volume-label').textContent=$('announcement-volume').value+'%';if(announceGain)announceGain.gain.value=Number($('announcement-volume').value)/100;};
document.addEventListener('echo:audio-focus',()=>{if(audioBusy())stopAnnouncement();});
document.addEventListener('echo:conversation',()=>{if(audioBusy())stopAnnouncement();});
player.addEventListener('play',()=>stopAnnouncement());
document.addEventListener('visibilitychange',()=>{if(document.hidden)stopAnnouncement();});
window.addEventListener('pagehide',()=>{announceEnabled=false;stopAnnouncement();});
setInterval(pollAnnouncements,2000);

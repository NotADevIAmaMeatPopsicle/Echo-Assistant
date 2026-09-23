/* Group existing controls without replacing their forms, state or permissions. */
'use strict';
(()=>{
  const host=$('page-settings'),main=document.querySelector('main');
  const sections=[
    {id:'display',label:'Display',icon:'sun',title:'Make the screen yours.',description:'Home tiles, clocks, photos and when the display rests.',anchors:['#clock24','#screen-form','#use-album']},
    {id:'voice',label:'Voice',icon:'mic',title:'Microphone, voice & alerts.',description:'Choose what Echo hears and where replies and alarms play.',anchors:['#pi-voice-form','#pi-alert-form']},
    {id:'music',label:'Music',icon:'music',title:'Your music, your speakers.',description:'Spotify, shared playback, and radio presets.',anchors:['#pi-audio-form','#group-local-form','#group-music-form','#radio-presets']},
    {id:'calling',label:'Calls & camera',icon:'chat',title:'A little closer.',description:'Video calls, room announcements and camera motion wake.',anchors:['#calling-configure','#announcement-listen','#audio-room-form','#deck-camera-presence']},
    {id:'home',label:'Home',icon:'home',title:'Connect your home.',description:'Google Calendar and the calendars, cameras and sensors shared with Echo.',anchors:['#google-calendar-card','#source-load']},
    {id:'access',label:'Access',icon:'check',title:'Choose who can use Echo.',description:'Pair displays, manage personal accounts and set device permissions.',anchors:['#pairing-form','#members-card','#mini-access-card']},
    {id:'system',label:'System',icon:'settings',title:'Your Echo workspace.',description:'Connection status, assistant models and advanced configuration.',anchors:['#settings-overview','#settings-workspace']}
  ];
  const bar=document.createElement('div');bar.className='settings-nav';bar.dataset.noPageSwipe='';
  const tabs=document.createElement('div');tabs.className='settings-tabs';tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Settings sections');
  bar.append(tabs);host.prepend(bar);
  const empty=document.createElement('p');empty.className='soft settings-empty';empty.textContent='Checking the settings available on this display…';empty.hidden=true;
  host.append(empty);
  let selected='display';
  for(const section of sections){
    const tab=document.createElement('button');tab.type='button';tab.id='settings-tab-'+section.id;tab.className='settings-tab';tab.dataset.settingsTab=section.id;
    tab.setAttribute('role','tab');tab.setAttribute('aria-controls','settings-panel-'+section.id);tab.setAttribute('aria-selected','false');tab.tabIndex=-1;
    tab.innerHTML=icon(section.icon)+`<span>${section.label}</span>`;tabs.append(tab);
    const panel=document.createElement('section');panel.id='settings-panel-'+section.id;panel.className='settings-panel';panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',tab.id);panel.tabIndex=0;panel.hidden=true;
    const heading=document.createElement('div');heading.className='settings-heading';
    const title=document.createElement('h2');title.textContent=section.title;const note=document.createElement('p');note.textContent=section.description;heading.append(title,note);
    const grid=document.createElement('div');grid.className='settings-grid';panel.append(heading,grid);host.append(panel);
    Object.assign(section,{tab,panel,grid});
    tab.onclick=()=>select(section.id,{scroll:true});
  }
  function place(card,section){
    if(card.dataset.settingsSection)return;
    card.dataset.settingsSection=section.id;section.grid.append(card);
  }
  // Move the actual elements once: drafts and installed event handlers survive.
  for(const section of sections)for(const selector of section.anchors){
    const card=host.querySelector(selector)?.closest('.card');if(card)place(card,section);
  }
  function remaining(){
    for(const card of host.querySelectorAll(':scope > .card,:scope > .two-columns > .card')){
      const section=sections.find(s=>s.anchors.some(a=>card.matches(a)||card.querySelector(a)))||sections.at(-1);place(card,section);
    }
    for(const wrapper of host.querySelectorAll(':scope > .two-columns'))if(!wrapper.children.length)wrapper.remove();
  }
  remaining();
  for(const selector of ['#pi-voice-form','#audio-room-form','#pairing-form','#group-music-form','#source-form','#calling-config-form'])host.querySelector(selector)?.closest('.card').classList.add('settings-wide');
  const available=section=>[...section.grid.children].some(card=>!card.hidden&&getComputedStyle(card).display!=='none');
  function select(id,{scroll=false,focus=false}={}){
    const target=sections.find(s=>s.id===id&&!s.tab.hidden);if(!target)return false;
    const changed=selected!==id;selected=id;
    for(const section of sections){const active=section===target;section.panel.hidden=!active;section.tab.setAttribute('aria-selected',String(active));section.tab.tabIndex=active?0:-1;}
    if(changed)document.dispatchEvent(new CustomEvent('echo:settings-tab',{detail:id}));
    if(scroll){main.scrollTop=0;target.tab.scrollIntoView({block:'nearest',inline:'nearest'});}
    if(focus)target.tab.focus({preventScroll:true});
    return true;
  }
  function sync(){
    for(const section of sections)section.tab.hidden=!available(section);
    const visible=sections.filter(s=>!s.tab.hidden);empty.hidden=!!visible.length;bar.hidden=!visible.length;
    const current=visible.find(s=>s.id===selected)||visible[0];
    if(current)select(current.id);else for(const section of sections)section.panel.hidden=true;
  }
  tabs.addEventListener('keydown',event=>{
    const visible=sections.filter(s=>!s.tab.hidden),index=visible.findIndex(s=>s.tab===event.target);if(index<0)return;
    let next;if(event.key==='ArrowRight')next=(index+1)%visible.length;if(event.key==='ArrowLeft')next=(index+visible.length-1)%visible.length;
    if(event.key==='Home')next=0;if(event.key==='End')next=visible.length-1;
    if(next!==undefined){event.preventDefault();select(visible[next].id,{scroll:true,focus:true});}
  });
  window.EchoSettings={open(id,target){
    page('settings');sync();if(!select(id,{scroll:true}))return false;
    const element=typeof target==='string'?$(target):target;
    if(element&&!element.hidden)requestAnimationFrame(()=>element.scrollIntoView({block:'start'}));
    return true;
  }};
  // Optional modules may append a card later. Keep their own hidden state intact.
  new MutationObserver(()=>{remaining();sync();}).observe(host,{childList:true});
  extensions.push(sync);
  document.addEventListener('echo:page',event=>{if(event.detail==='settings')sync();});
  sync();
})();

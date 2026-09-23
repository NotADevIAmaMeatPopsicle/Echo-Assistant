/* Public directory discovery; favorites contain station metadata, never account data. */
(()=>{
  'use strict';
  const card=document.createElement('article');card.className='card';
  card.innerHTML='<span class="eyebrow">LIVE RADIO</span><h2>Find your frequency.</h2><form id="radio-search" class="library-filters"><label>Station<input id="radio-query" type="search" maxlength="100" placeholder="Station name"></label><label>Country<select id="radio-country"><option value="">Worldwide</option><option value="US">United States</option><option value="CA">Canada</option><option value="GB">United Kingdom</option><option value="AU">Australia</option><option value="DE">Germany</option><option value="FR">France</option></select></label><label>Genre<select id="radio-genre"><option value="">All genres</option><option>jazz</option><option>classical</option><option>rock</option><option>pop</option><option>electronic</option><option>ambient</option><option>news</option><option>country</option><option>hip hop</option></select></label><button class="pill primary" type="submit">Find stations</button></form><div class="row wrap"><button id="radio-popular" class="pill">Popular</button><button id="radio-favorites" class="pill">Favorites</button></div><p id="radio-discovery-status" class="soft" role="status"></p><div id="radio-results" class="library-results"></div><button id="radio-more" class="pill" hidden>More stations</button><p class="tiny soft">Directory: Radio Browser. Live streams play on this display. Favorites are saved in this browser.</p>';
  $('local-panel').prepend(card);
  let rows=[],serial=0,loaded=false,view='directory',next=0,favoriteKey='';
  function key(){return 'echo-radio-favorites-v1:'+JSON.stringify([data.session?.role,data.session?.receiver_id,data.session?.member]);}
  function valid(s){try{const u=new URL(s.url);return typeof s.name==='string'&&s.name.length<=80&&u.protocol==='https:'&&!u.username&&!u.password&&s.url.length<=2048;}catch{return false;}}
  function favorites(){try{return JSON.parse(localStorage.getItem(key())||'[]').filter(valid).slice(0,50);}catch{return [];}}
  function draw(){
    const saved=new Set(favorites().map(s=>s.url));
    $('radio-results').innerHTML=rows.map((s,i)=>`<article class="library-item"><div class="library-monogram" aria-hidden="true">FM</div><div class="library-item-text"><strong>${esc(s.name)}</strong><span class="tiny soft">${esc([s.country,s.tags,s.codec,s.bitrate?s.bitrate+' kbps':''].filter(Boolean).join(' · '))}</span></div><button class="pill" data-radio-star="${i}" aria-label="${saved.has(s.url)?'Remove favorite':'Save favorite'}: ${esc(s.name)}" aria-pressed="${saved.has(s.url)}">${saved.has(s.url)?'★':'☆'}</button><button class="pill primary" data-directory-play="${i}" ${data.health?.display_demo?'disabled':''}>Play</button></article>`).join('')||'<p class="soft">'+(view==='favorites'?'Save stations with the star to find them here.':'No matching stations. Try a different name or genre.')+'</p>';
  }
  async function search(append=false){
    view='directory';loaded=true;const request=++serial;
    $('radio-discovery-status').textContent='Finding stations…';$('radio-more').hidden=true;
    const params=new URLSearchParams({q:$('radio-query').value.trim(),country:$('radio-country').value,tag:$('radio-genre').value,offset:String(append?next:0)});
    try{const result=await api('/v1/radio/stations?'+params);if(request!==serial)return;
      const items=result.items.filter(valid);rows=append?[...rows,...items.filter(s=>!rows.some(r=>r.url===s.url))]:items;next=result.next_offset;
      $('radio-more').hidden=!result.more;$('radio-discovery-status').textContent=`${rows.length} stations · Choose Play to tune in`;draw();
    }catch(error){if(request===serial)$('radio-discovery-status').textContent=error.message;}
  }
  $('radio-search').onsubmit=e=>{e.preventDefault();void search();};
  $('radio-popular').onclick=()=>{$('radio-search').reset();void search();};
  $('radio-more').onclick=()=>void search(true);
  $('radio-favorites').onclick=()=>{serial++;view='favorites';rows=favorites();$('radio-more').hidden=true;$('radio-discovery-status').textContent='Your favorite stations';draw();};
  $('radio-results').onclick=e=>{
    const star=e.target.closest('[data-radio-star]'),play=e.target.closest('[data-directory-play]');
    if(star){const s=rows[Number(star.dataset.radioStar)],saved=favorites(),exists=saved.some(x=>x.url===s.url);if(!exists&&saved.length>=50)return toast('You can save up to 50 favorites.');try{localStorage.setItem(key(),JSON.stringify(exists?saved.filter(x=>x.url!==s.url):[...saved,s]));if(view==='favorites')rows=favorites();draw();}catch{toast('This browser could not save favorites.');}}
    if(play&&!data.health?.display_demo){const s=rows[Number(play.dataset.directoryPlay)];loadMedia({kind:'radio',...s});void playDisplayMedia();mediaCard.scrollIntoView({block:'nearest',behavior:'smooth'});}
  };
  document.addEventListener('echo:music-tab',e=>{if(e.detail==='local'&&!loaded)void search();});
  extensions.push(()=>{if(key()!==favoriteKey){favoriteKey=key();serial++;loaded=false;rows=[];$('radio-results').replaceChildren();$('radio-more').hidden=true;}});
})();

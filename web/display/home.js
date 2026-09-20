/* Only tile choices are stored here. Device state and music metadata stay in memory. */
'use strict';
const homeTileChoices = [
  {id:'clock', name:'Clock & Echo', icon:'home', note:'Time and assistant status'},
  {id:'weather', name:'Weather', icon:'sun', note:'Conditions outside'},
  {id:'rooms', name:'Rooms', icon:'light', note:'Your lights at a glance'},
  {id:'music', name:'Music', icon:'music', note:'Artwork and playback'},
  {id:'timers', name:'Timers', icon:'timer', note:'The next countdown'},
  {id:'lists', name:'Lists', icon:'list', note:'Shopping, tasks and notes'},
  {id:'climate', name:'Thermostat', icon:'sun', note:'Temperature and mode'},
  {id:'empty', name:'Empty', icon:'minus', note:'Leave this space clear'}
];
const homeTileDefaults = ['clock','weather','rooms','music'];
const homeTilePositions = ['Top left','Top right','Bottom left','Bottom right'];
const homeTileStorage = 'echo-display-home-tiles-v1';
let homeTiles = [...homeTileDefaults], homeTileDraft, homeTileSlot = 0, homeCoverSource = '';
try {
  const saved = JSON.parse(localStorage.getItem(homeTileStorage));
  if (Array.isArray(saved) && saved.length === 4 && saved.every(id => homeTileChoices.some(c => c.id === id)) &&
      new Set(saved.filter(id => id !== 'empty')).size === saved.filter(id => id !== 'empty').length) homeTiles = saved;
} catch { /* Storage is optional; keep the working default. */ }

const homeGrid = document.querySelector('.home-grid');
const homeCards = {
  clock:homeGrid.querySelector('.hero'), weather:homeGrid.querySelector('.weather'),
  rooms:homeGrid.querySelector('.room-summary'), timers:homeGrid.querySelector('.next-up')
};
for (const [id, markup] of Object.entries({
  music:`<div class="row spread"><span class="eyebrow">MUSIC</span><span id="home-music-state" class="tiny soft"></span></div>
    <div class="home-track"><div class="home-cover">${icon('music')}<img id="home-music-cover" alt="" hidden></div><div><h2 id="home-music-title">Your next favourite.</h2><p id="home-music-artist" class="soft">Choose this display in Spotify.</p></div></div>
    <div class="row spread home-tile-footer"><button class="text-button" data-page="music">Open music ↗</button><button id="home-music-toggle" class="icon-button" aria-label="Play music" disabled>${icon('play')}</button></div>`,
  lists:`<span class="eyebrow">LISTS</span><h2 id="home-list-count" class="home-glance">One less thing.</h2><p id="home-list-detail" class="soft"></p><button class="text-button home-tile-footer" data-page="lists">Open lists ↗</button>`,
  climate:`<span class="eyebrow">THERMOSTAT</span><h2 id="home-climate-temp" class="home-glance">—</h2><p id="home-climate-detail" class="soft"></p><button class="text-button home-tile-footer" data-page="rooms">Climate controls ↗</button>`
})) {
  const card = document.createElement('article'); card.className = `card home-${id}`; card.innerHTML = markup;
  homeGrid.append(card); homeCards[id] = card;
}
for (const [id, card] of Object.entries(homeCards)) card.dataset.homeTile = id;

const editHome = document.createElement('button');
editHome.id = 'edit-home'; editHome.className = 'pill home-edit'; editHome.innerHTML = `${icon('settings')}<span>Edit Home</span>`;
document.querySelector('.header-right').prepend(editHome);
const editHomeSettings = document.createElement('button');
editHomeSettings.id = 'edit-home-settings'; editHomeSettings.className = 'pill'; editHomeSettings.textContent = 'Choose Home tiles';
$('clock24').closest('label').before(editHomeSettings);

const homeTileDialog = document.createElement('dialog'); homeTileDialog.id = 'home-tile-dialog';
homeTileDialog.setAttribute('aria-labelledby','home-tile-heading');
homeTileDialog.innerHTML = `<div class="row spread"><div><span class="eyebrow">MAKE ROOM FOR YOUR DAY</span><h2 id="home-tile-heading">Your Home, your tiles.</h2></div><button id="home-tiles-close" class="icon-button" aria-label="Close tile picker">×</button></div>
  <p class="soft home-picker-intro">Pick a position, then choose what belongs there.</p>
  <div class="home-picker-body"><div id="home-tile-slots" aria-label="Home tile positions"></div><div><h3 id="home-slot-heading">Top left</h3><div id="home-tile-options" aria-labelledby="home-slot-heading"></div></div></div>
  <p id="home-tile-feedback" class="tiny soft" role="status">Choosing a tile already on Home swaps its position.</p>
  <div class="row spread home-picker-footer"><button id="home-tiles-reset" class="text-button">Reset layout</button><div class="row"><button id="home-tiles-cancel" class="pill">Cancel</button><button id="home-tiles-save" class="pill primary">Save layout</button></div></div>`;
document.body.append(homeTileDialog);
homeTilePositions.forEach((label, slot) => {
  const button = document.createElement('button'); button.type = 'button'; button.dataset.homeSlotChoice = slot;
  button.innerHTML = `<span>${label}</span><strong></strong>`;
  button.onclick = () => {homeTileSlot = slot; renderHomePicker();}; $('home-tile-slots').append(button);
});
homeTileChoices.forEach(choice => {
  const button = document.createElement('button'); button.type = 'button'; button.dataset.homeChoice = choice.id;
  button.innerHTML = `${choice.id === 'empty' ? '<span class="empty-tile-icon">−</span>' : icon(choice.icon)}<span><strong>${choice.name}</strong><small>${choice.note}</small></span>`;
  button.onclick = () => {
    const other = choice.id === 'empty' ? -1 : homeTileDraft.indexOf(choice.id), previous = homeTileDraft[homeTileSlot];
    if (other >= 0 && other !== homeTileSlot) homeTileDraft[other] = previous;
    homeTileDraft[homeTileSlot] = choice.id;
    $('home-tile-feedback').textContent = `${homeTilePositions[homeTileSlot]}: ${choice.name}.${other >= 0 && other !== homeTileSlot ? ' Existing tile positions swapped.' : ''}`;
    renderHomePicker();
  };
  $('home-tile-options').append(button);
});
function renderHomePicker() {
  homeTilePositions.forEach((_, slot) => {
    const b = document.querySelector(`[data-home-slot-choice="${slot}"]`);
    b.querySelector('strong').textContent = homeTileChoices.find(c => c.id === homeTileDraft[slot]).name;
    b.setAttribute('aria-pressed', String(slot === homeTileSlot));
  });
  $('home-slot-heading').textContent = `Choose ${homeTilePositions[homeTileSlot].toLowerCase()}`;
  document.querySelectorAll('[data-home-choice]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.homeChoice === homeTileDraft[homeTileSlot])));
}
function openHomePicker() {
  homeTileDraft = [...homeTiles]; homeTileSlot = 0; renderHomePicker();
  $('home-tile-feedback').textContent = 'Choosing a tile already on Home swaps its position.';
  homeTileDialog.showModal();
}
editHome.onclick = editHomeSettings.onclick = openHomePicker;
$('home-tiles-close').onclick = $('home-tiles-cancel').onclick = () => homeTileDialog.close();
$('home-tiles-reset').onclick = () => {homeTileDraft = [...homeTileDefaults]; renderHomePicker(); $('home-tile-feedback').textContent = 'Default layout ready. Save to apply it.';};
$('home-tiles-save').onclick = () => {
  homeTiles = [...homeTileDraft]; applyHomeTiles(); homeTileDialog.close();
  try {localStorage.setItem(homeTileStorage, JSON.stringify(homeTiles)); toast('Home layout saved on this display.');}
  catch {toast('Home layout changed for this session. Browser storage is unavailable.');}
  refresh();
};
function applyHomeTiles() {
  for (const [id, card] of Object.entries(homeCards)) {
    const slot = homeTiles.indexOf(id); card.hidden = slot < 0; delete card.dataset.homeSlot;
  }
  // DOM order follows visual order for keyboard and screen-reader navigation.
  homeTiles.forEach((id, slot) => {if (homeCards[id]) {homeCards[id].dataset.homeSlot = slot; homeGrid.append(homeCards[id]);}});
  renderHomeGlances(); renderHomeMusic();
}
function homeShowsMusic() {return !$('page-home').hidden && homeTiles.includes('music');}
function renderHomeMusic() {
  const state = fresh('nowPlaying') ? data.nowPlaying : {}, ready = fresh('timers') && fresh('nowPlaying');
  const title = ready ? state.title : '', status = ready ? state.status : 'unavailable';
  $('home-music-title').textContent = title || 'Your next favourite.';
  $('home-music-artist').textContent = title ? (state.artist || state.album || 'Spotify') : 'Open music to choose your next track.';
  $('home-music-state').textContent = !ready ? 'Unavailable' : state.ducked && status === 'playing' ? 'Lowered for Echo' : human(status);
  const toggle = $('home-music-toggle'), playing = status === 'playing';
  toggle.innerHTML = icon(playing ? 'pause' : 'play'); toggle.setAttribute('aria-label', playing ? 'Pause music' : 'Play music');
  toggle.disabled = busy || !ready || !state.available || !['playing','paused','connected','stopped'].includes(status);
  const art = ready && typeof state.artwork === 'string' && /^\/v1\/(?:display\/)?music\/artwork\/[a-f0-9]{64}$/.test(state.artwork) ? state.artwork : '';
  if (art !== homeCoverSource) {
    homeCoverSource = art; const image = $('home-music-cover'); image.hidden = true;
    image.onload = () => {if (image.getAttribute('src') === homeCoverSource) image.hidden = false;};
    image.onerror = () => {image.hidden = true;};
    if (art) image.src = art; else image.removeAttribute('src');
  }
}
$('home-music-toggle').onclick = () => sendMusic('toggle');
function renderHomeGlances() {
  const household = fresh('household') ? data.household : null;
  const items = household?.items || [], open = items.filter(i => !i.done && i.kind !== 'notes');
  $('home-list-count').textContent = !household ? 'Lists unavailable' : open.length ? `${open.length} to do` : 'All caught up.';
  $('home-list-detail').textContent = household ? `${open.filter(i => i.kind === 'shopping').length} shopping · ${open.filter(i => i.kind === 'tasks').length} tasks · ${items.filter(i => i.kind === 'notes').length} notes` : 'Reconnect to see your saved lists.';
  const device = fresh('home') ? data.home?.devices?.thermostat : null, attrs = device?.attributes || {}, available = device?.status === 'available';
  $('home-climate-temp').textContent = available && Number.isFinite(attrs.current_temperature) ? `${attrs.current_temperature}${attrs.temperature_unit || '°'}` : '—';
  $('home-climate-detail').textContent = available ? `${human(device.state)}${Number.isFinite(attrs.temperature) ? ` · Target ${attrs.temperature}${attrs.temperature_unit || '°'}` : ''}` : 'Thermostat unavailable';
}
document.addEventListener('echo:page', event => {
  editHome.hidden = event.detail !== 'home';
  if (homeTileDialog.open) homeTileDialog.close();
});
extensions.push(renderHomeGlances);
applyHomeTiles();

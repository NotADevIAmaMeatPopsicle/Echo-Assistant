'use strict';
endpoints.details='/v1/display/home'; pageEndpoints.details='rooms';
const detailCard=document.createElement('article'); detailCard.className='card detail-card';
detailCard.innerHTML='<div class="row spread"><div><span class="eyebrow">THE FINER DETAILS</span><h2>Individual devices</h2></div><a class="text-button" href="/devices">Permissions ↗</a></div><label>Device<select id="detail-device"><option>No devices loaded</option></select></label><div id="detail-controls"></div>';
$('page-rooms').append(detailCard);
let detailDevice='';
function field(name,label,type,value,extra='') { return `<label>${label}<input id="detail-${name}" type="${type}" value="${esc(value ?? '')}" ${extra} required></label>`; }
function submitControl(command,content) { return `<form data-detail-form="${command}" class="detail-form">${content}<button class="pill" type="submit" data-requires="details">Apply</button></form>`; }
function directControl(command,label,value) { return `<button class="pill" type="button" data-detail-command="${command}" ${value!==undefined ? `data-value="${esc(JSON.stringify(value))}"` : ''} data-requires="details">${label}</button>`; }
function renderDetails() {
  if ($('page-rooms').hidden || detailCard.contains(document.activeElement)) return;
  const devices=(data.details?.devices || []).filter(d=>['light','switch','climate','media_player','scene'].includes(d.domain));
  if (!devices.some(d=>d.entity_id===detailDevice)) detailDevice=devices[0]?.entity_id || '';
  $('detail-device').innerHTML=devices.map(d=>`<option value="${esc(d.entity_id)}" ${d.entity_id===detailDevice ? 'selected' : ''}>${esc(d.name)}${d.area ? ' · '+esc(d.area) : ''}</option>`).join('') || '<option>No permitted devices available</option>';
  const device=devices.find(d=>d.entity_id===detailDevice);
  if (!device) { $('detail-controls').innerHTML=empty('Connect Home Assistant and assign device permissions in Devices.'); return; }
  const attrs=device.attributes || {}, modes=attrs.supported_color_modes || [], features=attrs.supported_features || 0;
  let content=`<p class="soft">${esc(human(device.state))} · ${device.access==='control' ? 'Control enabled' : 'Read only'}</p>`;
  if (['light','switch'].includes(device.domain)) content+='<div class="row">'+directControl('turn_on','On')+directControl('turn_off','Off')+'</div>';
  if (device.domain==='light') {
    if (modes.some(m=>['brightness','color_temp','hs','xy','rgb','rgbw','rgbww','white'].includes(m))) content+=submitControl('brightness',field('brightness','Brightness %','number',Number.isFinite(attrs.brightness) ? Math.round(attrs.brightness*100/255) : '', 'min="0" max="100" step="1"'));
    if (modes.includes('color_temp') && Number.isFinite(attrs.min_color_temp_kelvin) && Number.isFinite(attrs.max_color_temp_kelvin)) content+=submitControl('color_temperature',field('kelvin','Colour temperature (K)','number',attrs.color_temp_kelvin,`min="${attrs.min_color_temp_kelvin}" max="${attrs.max_color_temp_kelvin}" step="1"`));
    if (modes.some(m=>['hs','xy','rgb','rgbw','rgbww'].includes(m))) {
      const rgb=attrs.rgb_color, color=Array.isArray(rgb) && rgb.length===3 ? '#'+rgb.map(n=>Math.max(0,Math.min(255,Math.round(n))).toString(16).padStart(2,'0')).join('') : '#ffffff';
      content+=submitControl('color',field('color','Choose colour','color',color));
    }
    content+='<p class="tiny soft">Applying brightness or colour can turn a light on. Changes happen only when you press Apply.</p>';
  }
  if (device.domain==='climate') {
    if (Array.isArray(attrs.hvac_modes)) content+=submitControl('mode',`<label>Mode<select id="detail-mode">${attrs.hvac_modes.map(mode=>`<option value="${esc(mode)}" ${device.state===mode ? 'selected' : ''}>${esc(human(mode))}</option>`).join('')}</select></label>`);
    if (['°C','°F'].includes(attrs.temperature_unit) && Number.isFinite(attrs.min_temp) && Number.isFinite(attrs.max_temp)) {
      const bounds=`min="${attrs.min_temp}" max="${attrs.max_temp}" step="${Number.isFinite(attrs.target_temp_step) ? attrs.target_temp_step : .5}"`;
      if (device.state==='heat_cool') content+=submitControl('temperature_range',field('low','Low target '+esc(attrs.temperature_unit),'number',attrs.target_temp_low,bounds)+field('high','High target '+esc(attrs.temperature_unit),'number',attrs.target_temp_high,bounds));
      else content+=submitControl('temperature',field('temperature','Target '+esc(attrs.temperature_unit),'number',attrs.temperature,bounds));
    }
    content+=`<p class="soft tiny">${Number.isFinite(attrs.current_humidity) ? 'Humidity '+attrs.current_humidity+'% · ' : ''}${esc(human(attrs.hvac_action || device.state))}</p>`;
  }
  if (device.domain==='media_player') {
    const supported=[['play','Play',16384],['pause','Pause',1],['stop','Stop',4096],['previous','Previous',16],['next','Next',32],['turn_on','On',128],['turn_off','Off',256]];
    content+='<div class="row wrap">'+supported.filter(([, ,mask])=>features&mask).map(([action,label])=>directControl(action,label)).join('')+(features&8 ? directControl('mute',attrs.is_volume_muted ? 'Unmute' : 'Mute',!attrs.is_volume_muted) : '')+'</div>';
    if (features&4) content+=submitControl('volume',field('volume','Speaker volume %','number',Number.isFinite(attrs.volume_level) ? Math.round(attrs.volume_level*100) : '', 'min="0" max="100" step="1"'));
    if (attrs.media_title) content+=`<p class="soft">${esc(attrs.media_title)}</p>`;
  }
  if (device.domain==='scene') content+=directControl('activate','Activate scene');
  $('detail-controls').innerHTML=content;
  $('detail-controls').querySelectorAll('[data-requires]').forEach(button=>button.dataset.unavailable=String(device.access!=='control' || !device.available));
}
extensions.push(renderDetails);
$('detail-device').onchange=event=>{detailDevice=event.target.value; event.target.blur(); renderDetails(); guardButtons();};
function deviceCommand(command,value=null) {
  const device=data.details?.devices.find(d=>d.entity_id===detailDevice);
  if (!fresh('details') || !device || device.access!=='control' || !device.available) return;
  const unit=['temperature','temperature_range'].includes(command) ? device.attributes.temperature_unit : null;
  return action(()=>api('/v1/display/home/control',{revision:data.details.revision,entity_id:device.entity_id,action:command,value,unit}));
}
detailCard.addEventListener('submit',event=>{
  event.preventDefault(); const command=event.target.dataset.detailForm; if (!command) return;
  const ids={brightness:'brightness',color_temperature:'kelvin',color:'color',mode:'mode',temperature:'temperature',volume:'volume'};
  const value=command==='temperature_range' ? {low:Number($('detail-low').value),high:Number($('detail-high').value)} : ['color','mode'].includes(command) ? $('detail-'+ids[command]).value : Number($('detail-'+ids[command]).value);
  deviceCommand(command,value);
});
detailCard.addEventListener('click',event=>{const button=event.target.closest('[data-detail-command]'); if (button && !button.disabled) deviceCommand(button.dataset.detailCommand,button.dataset.value ? JSON.parse(button.dataset.value) : null);});

'use strict';
endpoints.album='/v1/display/photos';
const albumCard=document.createElement('article');albumCard.className='card pairing-card';
albumCard.innerHTML='<span class="eyebrow">A FAMILIAR VIEW</span><h2>Ambient photo album</h2><p class="soft">Saved on your Echo host, shared with paired displays. Photos are resized and location metadata is removed.</p><label class="check-label"><input id="use-album" type="checkbox">Use this album on this display</label><div id="album-owner" hidden><label class="file-button pill">Add photos to the album<input id="album-upload" type="file" accept="image/jpeg,image/png,image/webp" multiple hidden></label><p class="tiny soft">Up to 60 photos · 12 MB and 32 megapixels each. Uploading a photo shares it with paired displays.</p></div><p id="album-status" class="tiny soft"></p><div id="album-grid" class="album-grid"></div>';
$('page-settings').append(albumCard);
try{$('use-album').checked=localStorage.getItem('echo-use-album')==='true';}catch{}
function useAlbum(){if($('use-album').checked && data.album?.items.length){clearPhotos();photos=data.album.items.map(i=>i.url);}}
let albumSignature='';
extensions.push(()=>{
  const state=data.album, owner=data.session?.role==='owner';$('album-owner').hidden=!owner;
  $('album-status').textContent=state ? `${state.items.length} of ${state.limit} photos · ${state.storage==='encrypted' ? 'Encrypted host storage' : 'Temporary demo album'}` : 'Album unavailable.';
  const signature=JSON.stringify(state?.items || [])+owner;
  if(signature!==albumSignature){albumSignature=signature;
    $('album-grid').innerHTML=(state?.items || []).map((item,index)=>`<figure><img src="${esc(item.url)}" alt="Album photo ${index+1}" loading="lazy">${owner ? `<button class="pill" data-delete-photo="${item.id}" aria-label="Remove photo ${index+1}">Remove</button>` : ''}</figure>`).join('');
    if($('use-album').checked){clearPhotos();useAlbum();}
  }
});
$('use-album').onchange=()=>{try{localStorage.setItem('echo-use-album',String($('use-album').checked));}catch{}clearPhotos();useAlbum();};
$('album-upload').onchange=event=>{const files=[...event.target.files];event.target.value='';action(async()=>{
  if(files.length>60)throw new Error('Choose up to 60 photos at a time.');
  let count=0;
  for(const file of files){
    if(file.size>12000000 || !['image/jpeg','image/png','image/webp'].includes(file.type))throw new Error(`${count} uploaded. Choose JPEG, PNG, or WebP files under 12 MB.`);
    $('album-status').textContent=`Uploading ${count+1} of ${files.length}…`;
    const result=await fetch('/v1/display/photos',{method:'POST',credentials:'same-origin',headers:{'Content-Type':file.type,'X-Echo-Request':'1'},body:file,signal:AbortSignal.timeout(30000)});
    if(!result.ok){const body=await result.json();throw new Error(`${count} uploaded. ${body.detail || 'Upload failed.'}`);}count++;
  }
  return {text:`${count} photos saved to the album.`};
});};
albumCard.addEventListener('click',event=>{const button=event.target.closest('[data-delete-photo]');if(button)action(()=>api('/v1/display/photos/'+button.dataset.deletePhoto,{},'DELETE'),'Photo removed from the shared album.');});

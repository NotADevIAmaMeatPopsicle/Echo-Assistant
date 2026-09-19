'use strict';
const listEditor=document.createElement('dialog');
listEditor.innerHTML='<form id="list-edit-form"><h2>A small change.</h2><label>Item<textarea id="list-edit-text" maxlength="500" rows="4" required></textarea></label><div class="row"><button class="pill" type="button" id="list-edit-cancel">Cancel</button><button class="pill primary" type="submit" data-requires="household">Save item</button></div></form>';
document.body.append(listEditor);
let editingListItem=null;
function enhanceLists() {
  const items=(data.household?.items || []).filter(item=>item.kind===kind);
  $('household-items').querySelectorAll('.household-item').forEach((row,index)=>{
    if(row.querySelector('.list-item-actions'))return;
    const item=items[index]; if(!item)return;
    const controls=document.createElement('div'); controls.className='list-item-actions';
    controls.innerHTML=`<button class="text-button" data-edit-item="${item.id}" data-requires="household">Edit</button><button class="text-button" data-move-item="${item.id}" data-position="${index-1}" data-requires="household" data-unavailable="${index===0}" aria-label="Move ${esc(item.text)} up">↑</button><button class="text-button" data-move-item="${item.id}" data-position="${index+1}" data-requires="household" data-unavailable="${index===items.length-1}" aria-label="Move ${esc(item.text)} down">↓</button>`;
    row.insertBefore(controls,row.querySelector('.delete-button'));
  });
}
extensions.push(enhanceLists);
$('household-items').addEventListener('click',event=>{
  const button=event.target.closest('button'); if(!button || button.disabled || !fresh('household'))return;
  if(button.dataset.editItem){const item=data.household.items.find(i=>i.id===button.dataset.editItem); if(!item)return; editingListItem={id:item.id,revision:data.household.revision};$('list-edit-text').value=item.text;listEditor.showModal();}
  if(button.dataset.moveItem) action(()=>api('/v1/household/'+button.dataset.moveItem,{revision:data.household.revision,position:Number(button.dataset.position)},'PATCH'),'List order saved.');
});
$('list-edit-cancel').onclick=()=>listEditor.close();
$('list-edit-form').onsubmit=event=>{event.preventDefault();if(!editingListItem || !fresh('household'))return;action(async()=>{await api('/v1/household/'+editingListItem.id,{revision:editingListItem.revision,text:$('list-edit-text').value.trim()},'PATCH');listEditor.close();editingListItem=null;},'Item updated.');};

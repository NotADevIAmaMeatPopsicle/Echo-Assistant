/* Touch page navigation shares the drawer order, without claiming control gestures. */
'use strict';
(() => {
  const main = document.querySelector('main'), contacts = new Set();
  const excluded = 'button,a,input,textarea,select,label,dialog,[contenteditable]:not([contenteditable="false"]),[role="slider"],[data-no-page-swipe],#chat-keyboard,video,audio,canvas';
  let gesture, suppressClickUntil = 0;
  document.addEventListener('pointerdown', event => {
    suppressClickUntil = 0; // A new deliberate tap is not the preceding swipe's release.
    if (!['touch','pen'].includes(event.pointerType)) return;
    contacts.add(event.pointerId);
    if (contacts.size !== 1) {gesture = null; return;}
    const target = event.target;
    if (!main.contains(target) || target.closest(excluded) || document.querySelector('dialog[open]') || !$('ambient').hidden) return;
    // A horizontally scrollable child owns horizontal gestures.
    for (let node = target; node && node !== main; node = node.parentElement) {
      if (node.scrollWidth > node.clientWidth + 4 && ['auto','scroll'].includes(getComputedStyle(node).overflowX)) return;
    }
    gesture = {id:event.pointerId, x:event.clientX, y:event.clientY, at:performance.now(), page:location.hash};
  }, {passive:true});
  document.addEventListener('pointermove', event => {
    if (!gesture || gesture.id !== event.pointerId) return;
    const dx = Math.abs(event.clientX - gesture.x), dy = Math.abs(event.clientY - gesture.y);
    if (dy > 20 && dy > dx * .65) gesture = null;
  }, {passive:true});
  document.addEventListener('pointercancel', event => {contacts.delete(event.pointerId); gesture = null;}, {passive:true});
  document.addEventListener('pointerup', event => {
    contacts.delete(event.pointerId); const start = gesture; gesture = null;
    if (!start || start.id !== event.pointerId || start.page !== location.hash || document.querySelector('dialog[open]') || !$('ambient').hidden) return;
    const dx = event.clientX - start.x, dy = event.clientY - start.y;
    if (Math.abs(dx) < Math.max(70, Math.min(110, main.clientWidth * .12)) || Math.abs(dx) < Math.abs(dy) * 2 || performance.now() - start.at > 1200) return;
    suppressClickUntil = performance.now() + 450;
    const pages = [...document.querySelectorAll('#navigation [data-page]')].filter(b=>!b.hidden&&(!window.echoAllowedPages||window.echoAllowedPages.has(b.dataset.page))).map(b => b.dataset.page);
    const index = pages.indexOf(location.hash.slice(1)), next = index + (dx < 0 ? 1 : -1);
    if (index < 0 || next < 0 || next >= pages.length) return;
    page(pages[next]);
    if (!matchMedia('(prefers-reduced-motion: reduce)').matches) {
      $(`page-${pages[next]}`).animate([{opacity:.6,transform:`translateX(${dx < 0 ? 22 : -22}px)`},{opacity:1,transform:'translateX(0)'}],{duration:180,easing:'ease-out'});
    }
  }, {passive:true});
  // Do not let the release of a swipe click a control on the newly shown page.
  document.addEventListener('click', event => {
    if (performance.now() < suppressClickUntil && event.detail !== 0) {event.preventDefault(); event.stopImmediatePropagation();}
  }, true);
  window.addEventListener('blur', () => {contacts.clear(); gesture = null;});
  document.addEventListener('echo:page', () => {gesture = null;});
})();

/* The navigation starts hidden; a top-edge pull or the visible tab opens it. */
(() => {
  const rail=document.querySelector('.rail'),pull=$('nav-pull'),backdrop=$('nav-backdrop');
  let gesture=null,suppressClickUntil=0;
  function setOpen(open){
    document.body.classList.toggle('nav-open',open);
    rail.inert=!open;
    rail.setAttribute('aria-hidden',String(!open));
    pull.setAttribute('aria-expanded',String(open));
    backdrop.hidden=!open;
    if(!open&&rail.contains(document.activeElement))pull.focus({preventScroll:true});
  }
  pull.addEventListener('click',()=>setOpen(!document.body.classList.contains('nav-open')));
  $('nav-close').addEventListener('click',()=>setOpen(false));
  backdrop.addEventListener('click',()=>setOpen(false));
  rail.addEventListener('click',event=>{
    if(event.target.closest('[data-page],a.brand'))setOpen(false);
  });
  document.addEventListener('echo:page',()=>setOpen(false));
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape'&&document.body.classList.contains('nav-open')){
      event.preventDefault();setOpen(false);
    }
  });
  document.addEventListener('pointerdown',event=>{
    suppressClickUntil=0; // A fresh tap is not the previous swipe's release.
    if(!['touch','pen'].includes(event.pointerType)||document.querySelector('dialog[open]')||!$('ambient').hidden)return;
    const open=document.body.classList.contains('nav-open');
    if((open&&rail.contains(event.target))||(!open&&event.clientY<=36))
      gesture={id:event.pointerId,x:event.clientX,y:event.clientY,open,at:performance.now()};
  },{passive:true});
  document.addEventListener('pointercancel',()=>{gesture=null;},{passive:true});
  document.addEventListener('pointerup',event=>{
    const start=gesture;gesture=null;
    if(!start||start.id!==event.pointerId||performance.now()-start.at>1300)return;
    const dx=event.clientX-start.x,dy=event.clientY-start.y;
    if(Math.abs(dy)<70||Math.abs(dy)<Math.abs(dx)*1.4)return;
    if((start.open&&dy<0)||(!start.open&&dy>0)){
      suppressClickUntil=performance.now()+120;
      setOpen(!start.open);
    }
  },{passive:true});
  document.addEventListener('click',event=>{
    if(performance.now()<suppressClickUntil&&event.detail!==0){
      event.preventDefault();event.stopImmediatePropagation();
    }
  },true);
  window.addEventListener('blur',()=>{gesture=null;});
})();

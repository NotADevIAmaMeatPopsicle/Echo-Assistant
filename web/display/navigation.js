/* Touch page navigation shares the sidebar order, without claiming control gestures. */
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
    const pages = [...document.querySelectorAll('#navigation [data-page],.rail-settings[data-page]')].filter(b=>b.getClientRects().length&&(!window.echoAllowedPages||window.echoAllowedPages.has(b.dataset.page))).map(b => b.dataset.page);
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

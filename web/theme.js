/* Appearance is a local display preference, never an account credential. */
(() => {
  'use strict';
  const key = 'echo-ui-theme';
  const themes = [
    {id: 'echo', name: 'Echo Midnight', note: 'The original calm blue-green look.'},
    {id: 'forest', name: 'Totoro Forest', note: 'A soft woodland-inspired mood.'},
    {id: 'pixel', name: 'Super Mario World', note: 'Bouncy sky, meadow and pixel edges.'},
    {id: 'jaunty', name: 'Jaunty Light', note: 'Sunny, clear and full of bounce.'},
    {id: 'fruit', name: 'Fruit Ninja Arcade', note: 'Juicy colors and bold arcade energy.'}
  ];
  const valid = new Set(themes.map(theme => theme.id));
  let current = 'echo';
  try { const saved = localStorage.getItem(key); if (valid.has(saved)) current = saved; } catch { /* Session-only fallback. */ }
  document.documentElement.dataset.echoTheme = current;
  function select(id) {
    if (!valid.has(id)) return;
    current = id;
    document.documentElement.dataset.echoTheme = id;
    for (const button of document.querySelectorAll('[data-theme-choice]')) {
      button.setAttribute('aria-pressed', String(button.dataset.themeChoice === id));
    }
    const status = document.getElementById('theme-status');
    if (status) status.textContent = `${themes.find(theme => theme.id === id).name} selected for this browser.`;
    try { localStorage.setItem(key, id); }
    catch { if (status) status.textContent += ' This browser will keep it only until the page closes.'; }
  }
  function mount() {
    for (const picker of document.querySelectorAll('[data-theme-picker]')) {
      picker.setAttribute('role', 'group');
      picker.setAttribute('aria-label', 'Choose an interface theme');
      for (const theme of themes) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'theme-choice';
        button.dataset.themeChoice = theme.id;
        button.setAttribute('aria-pressed', String(theme.id === current));
        const preview = document.createElement('span');
        preview.className = 'theme-choice-preview';
        preview.setAttribute('aria-hidden', 'true');
        const text = document.createElement('span');
        const name = document.createElement('strong');
        name.textContent = theme.name;
        const note = document.createElement('small');
        note.textContent = theme.note;
        text.append(name, note);
        button.append(preview, text);
        picker.append(button);
      }
    }
    document.addEventListener('click', event => {
      const button = event.target.closest('[data-theme-choice]');
      if (button) select(button.dataset.themeChoice);
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once: true});
  else mount();
  window.EchoTheme = {select, current: () => current};
})();

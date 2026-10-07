/* Keep the existing settings form and save behavior; present it as clear panes. */
(() => {
  'use strict';
  const form = document.getElementById('settings-panel');
  if (!form) return;
  if (location.pathname === '/settings') document.body.classList.add('settings-workspace-view');
  const definitions = [
    {id: 'appearance', title: 'Appearance', note: 'Theme and visual style'},
    {id: 'conversation', title: 'Conversation', note: 'Agent, provider and model'},
    {id: 'personality', title: 'Personality', note: 'Tone and response length'},
    {id: 'speech', title: 'Voice & speech', note: 'Speaking and recognition'},
    {id: 'knowledge', title: 'Knowledge & memory', note: 'Web lookup and saved facts'}
  ];
  const fieldsets = [...form.querySelectorAll(':scope > fieldset')];
  if (fieldsets.length !== definitions.length) return;
  const layout = document.createElement('div');
  layout.className = 'browser-settings-layout';
  const navigation = document.createElement('div');
  navigation.className = 'browser-settings-nav';
  const heading = document.createElement('div');
  heading.className = 'browser-settings-intro';
  heading.innerHTML = '<span class="eyebrow">YOUR SETTINGS</span><h3>Find your way.</h3><p>Choose a topic. Your changes to Echo’s assistant settings save together.</p>';
  const search = document.createElement('input');
  search.type = 'search';
  search.placeholder = 'Find a setting…';
  search.setAttribute('aria-label', 'Find a setting');
  search.autocomplete = 'off';
  const results = document.createElement('div');
  results.className = 'browser-settings-results';
  results.hidden = true;
  const tabs = document.createElement('div');
  tabs.className = 'browser-settings-tabs';
  tabs.setAttribute('role', 'tablist');
  tabs.setAttribute('aria-label', 'Assistant settings sections');
  navigation.append(heading, search, results, tabs);
  const content = document.createElement('div');
  content.className = 'browser-settings-content';
  layout.append(navigation, content);
  form.querySelector('.section-heading').after(layout);
  let selected = 'appearance';
  try { selected = sessionStorage.getItem('echo-settings-section') || selected; } catch { /* Optional convenience. */ }
  definitions.forEach((item, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'browser-settings-tab';
    button.id = `browser-settings-tab-${item.id}`;
    button.setAttribute('role', 'tab');
    button.setAttribute('aria-controls', `browser-settings-pane-${item.id}`);
    button.innerHTML = `<strong>${item.title}</strong><small>${item.note}</small>`;
    const pane = document.createElement('section');
    pane.className = 'browser-settings-pane';
    pane.id = `browser-settings-pane-${item.id}`;
    pane.setAttribute('role', 'tabpanel');
    pane.setAttribute('aria-labelledby', button.id);
    pane.append(fieldsets[index]);
    tabs.append(button);
    content.append(pane);
    item.button = button;
    item.pane = pane;
    button.addEventListener('click', () => select(item.id));
  });
  function select(id, focus = false) {
    const chosen = definitions.find(item => item.id === id) || definitions[0];
    selected = chosen.id;
    definitions.forEach(item => {
      const active = item === chosen;
      item.pane.hidden = !active;
      item.button.setAttribute('aria-selected', String(active));
      item.button.tabIndex = active ? 0 : -1;
    });
    try { sessionStorage.setItem('echo-settings-section', selected); } catch { /* Optional convenience. */ }
    if (focus) chosen.button.focus();
  }
  search.addEventListener('input', () => {
    const query = search.value.trim().toLocaleLowerCase();
    results.replaceChildren();
    results.hidden = !query;
    tabs.hidden = !!query;
    if (!query) return;
    for (const item of definitions) {
      const terms = [item.title, item.note, ...[...item.pane.querySelectorAll('legend,label,[data-theme-choice]')].map(element => element.textContent)];
      if (!terms.join(' ').toLocaleLowerCase().includes(query)) continue;
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'browser-settings-result';
      button.textContent = `${item.title} · ${item.note}`;
      button.addEventListener('click', () => {
        select(item.id);
        search.value = '';
        search.dispatchEvent(new Event('input'));
        item.pane.scrollIntoView({block: 'start'});
      });
      results.append(button);
    }
    if (!results.children.length) {
      const empty = document.createElement('p');
      empty.textContent = 'No matching settings. Try another word.';
      results.append(empty);
    }
  });
  search.addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); results.querySelector('button')?.click(); }
    if (event.key === 'Escape') { search.value = ''; search.dispatchEvent(new Event('input')); search.blur(); }
  });
  tabs.addEventListener('keydown', event => {
    const index = definitions.findIndex(item => item.button === event.target);
    if (index < 0) return;
    let next;
    if (event.key === 'ArrowDown' || event.key === 'ArrowRight') next = (index + 1) % definitions.length;
    if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') next = (index + definitions.length - 1) % definitions.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = definitions.length - 1;
    if (next !== undefined) { event.preventDefault(); select(definitions[next].id, true); }
  });
  select(selected);
})();

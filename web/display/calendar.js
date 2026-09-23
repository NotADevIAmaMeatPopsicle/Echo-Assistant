/* A shared calendar page for the Deck and browser workspace. */
'use strict';
(() => {
  const screen = document.createElement('section');
  screen.id = 'page-calendar'; screen.className = 'page'; screen.hidden = true;
  screen.innerHTML = `
    <div class="calendar-toolbar">
      <div class="segmented" aria-label="Calendar view">
        <button type="button" data-calendar-view="month" class="selected" aria-pressed="true">Month</button>
        <button type="button" data-calendar-view="agenda" aria-pressed="false">Agenda</button>
      </div>
      <label class="calendar-filter"><span class="sr-only">Show calendar</span><select id="calendar-filter" aria-label="Show calendar"><option value="">All calendars</option></select></label>
      <button class="pill primary" id="calendar-page-new" type="button" disabled>+ New event</button>
    </div>
    <div class="calendar-layout">
      <article class="card calendar-month">
        <div class="calendar-month-heading">
          <div><span class="eyebrow">MAKE ROOM FOR WHAT MATTERS</span><h2 id="calendar-month-title"></h2></div>
          <div class="calendar-month-controls">
            <button class="icon-button" id="calendar-previous" type="button" aria-label="Previous month">‹</button>
            <button class="pill" id="calendar-today" type="button">Today</button>
            <button class="icon-button" id="calendar-next" type="button" aria-label="Next month">›</button>
          </div>
        </div>
        <div class="calendar-weekdays" aria-hidden="true">${['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map(day => `<span>${day}</span>`).join('')}</div>
        <div id="calendar-grid" class="calendar-grid" role="group" aria-label="Choose a date"></div>
        <p id="calendar-month-note" class="tiny soft"></p>
      </article>
      <article class="card calendar-agenda">
        <div class="calendar-agenda-heading"><span class="eyebrow" id="calendar-agenda-caption">ON YOUR CALENDAR</span><h2 id="calendar-day-title"></h2><p id="calendar-page-status" class="tiny soft" role="status"></p></div>
        <div id="calendar-day-events"></div>
        <div class="calendar-connections">
          <button class="text-button" id="calendar-connect" type="button" hidden>Connect Google Calendar ↗</button>
          <button class="text-button" id="calendar-sources" type="button" hidden>Choose shared calendars ↗</button>
          <button class="text-button" id="calendar-personal" type="button" hidden>My Google calendars ↗</button>
          <a class="text-button" id="calendar-workspace" href="/" hidden>Back to workspace ↗</a>
        </div>
      </article>
    </div>`;
  document.querySelector('main').append(screen);
  titles.calendar = 'A little space for your plans.';
  const nav = document.createElement('button'); nav.dataset.page = 'calendar';
  nav.innerHTML = icon('calendar') + '<span>Calendar</span>';
  dayNav.after(nav);
  const shortcut = document.createElement('button'); shortcut.type = 'button';
  shortcut.className = 'text-button'; shortcut.dataset.page = 'calendar'; shortcut.textContent = 'Open calendar ↗';
  createButton.after(shortcut);

  let selected = localDate(new Date()), month = selected.slice(0, 7), view = 'month', filter = '';
  let gridSignature = '', agendaSignature = '', filterSignature = '';
  const dateAtNoon = key => new Date(key + 'T12:00:00');
  const daysInMonth = () => new Date(Number(month.slice(0, 4)), Number(month.slice(5)), 0).getDate();
  const fullDate = key => dateAtNoon(key).toLocaleDateString(undefined, {weekday:'long', month:'long', day:'numeric', year:'numeric'});
  const monthTitle = () => dateAtNoon(month + '-01').toLocaleDateString(undefined, {month:'long', year:'numeric'});
  function updateEndpoint() {
    endpoints.calendarAgenda = '/v1/display/agenda?' + new URLSearchParams({start:month + '-01', days:daysInMonth()});
  }
  updateEndpoint(); pageEndpoints.calendarAgenda = 'calendar'; pageEndpoints.sources = ['day', 'calendar'];

  // End dates are exclusive. Local midnight boundaries preserve DST and keep
  // an event ending at midnight off the following day's list.
  function onDay(event, key) {
    if (event.all_day) return event.start <= key && event.end > key;
    const start = new Date(key + 'T00:00:00'), end = new Date(start); end.setDate(end.getDate() + 1);
    return new Date(event.start) < end && new Date(event.end) > start;
  }
  function changeMonth(delta) {
    const date = dateAtNoon(month + '-01'); date.setMonth(date.getMonth() + delta);
    month = localDate(date).slice(0, 7);
    selected = month + '-' + String(Math.min(Number(selected.slice(8)), daysInMonth())).padStart(2, '0');
    delete data.calendarAgenda; delete received.calendarAgenda; updateEndpoint(); renderCalendar(); void refresh();
  }
  function eventMarkup(event, day, sources) {
    const color = Math.max(0, sources.findIndex(source => source.entity_id === event.calendar)) % 6;
    const time = event.all_day ? 'All day' : localDate(new Date(event.start)) < day ? 'Continues' :
      new Date(event.start).toLocaleTimeString([], {hour:'numeric', minute:'2-digit', hour12:!preferences.clock24});
    return `<button type="button" class="calendar-entry calendar-color-${color}" data-calendar-event="${esc(event.id)}"><span class="calendar-entry-time">${esc(time)}</span><span class="calendar-entry-copy"><strong>${esc(event.title)}</strong><small>${esc(event.calendar_name)}${event.recurring ? ' · Repeats' : ''}</small>${event.location ? `<small>${esc(event.location)}</small>` : ''}</span><span aria-hidden="true">›</span></button>`;
  }
  function renderCalendar() {
    if (screen.hidden) return;
    const sources = fresh('sources') ? (data.sources.items || []).filter(source => source.kind === 'calendar') : [];
    if (filter && !sources.some(source => source.entity_id === filter)) filter = '';
    const nextFilter = JSON.stringify(sources.map(source => [source.entity_id, source.name]));
    if (nextFilter !== filterSignature) {
      $('calendar-filter').innerHTML = '<option value="">All calendars</option>' + sources.map(source => `<option value="${esc(source.entity_id)}">${esc(source.name)}</option>`).join('');
      filterSignature = nextFilter;
    }
    $('calendar-filter').value = filter;
    const state = fresh('calendarAgenda') ? data.calendarAgenda : null;
    const ids = new Set(sources.map(source => source.entity_id));
    const events = (state?.events || []).filter(event => ids.has(event.calendar) && (!filter || event.calendar === filter))
      .sort((a, b) => Number(b.all_day) - Number(a.all_day) || a.start.localeCompare(b.start) || a.title.localeCompare(b.title));
    const owner = data.session?.role === 'owner' && !data.session?.member;
    const personal = !!data.session?.member;
    const readOnly = personal || data.session?.profile?.mode === 'guest';
    $('calendar-connect').hidden = $('calendar-sources').hidden = $('calendar-workspace').hidden = !owner;
    $('calendar-personal').hidden = !personal;
    $('calendar-page-new').hidden = readOnly;
    $('calendar-page-new').disabled = !sources.some(source => source.writable && source.available);
    $('calendar-month-title').textContent = monthTitle();
    $('calendar-grid').setAttribute('aria-label', 'Choose a date in ' + monthTitle());
    $('calendar-day-title').textContent = view === 'month' ? dateAtNoon(selected).toLocaleDateString(undefined, {weekday:'long', month:'short', day:'numeric'}) : monthTitle();
    $('calendar-agenda-caption').textContent = view === 'month' ? selected === localDate(new Date()) ? 'TODAY, AT A GLANCE' : 'A LITTLE LOOK AHEAD' : 'YOUR MONTH, IN ORDER';
    const unavailable = !state || !fresh('sources') || ['unavailable','not_configured'].includes(state.status);
    $('calendar-page-status').textContent = !fresh('sources') || !state ? 'Loading your calendars. If this persists, check the host connection.' :
      !sources.length ? owner ? 'Connect a calendar, then choose what to share below.' : 'No calendars are shared with this screen. Choose sources in the owner workspace.' :
      unavailable ? 'Calendars could not be reached. Retrying automatically.' :
      state.status === 'partial' ? 'Some calendars are unavailable. Showing the events we could load.' :
      `${filter ? sources.find(source => source.entity_id === filter).name : 'Your selected calendars'} · ${Intl.DateTimeFormat().resolvedOptions().timeZone || 'Local time'}`;
    $('calendar-month-note').textContent = readOnly ? 'Read-only calendar · tap an event for details.' :
      !sources.some(source => source.writable && source.available) ? 'Event creation becomes available after a calendar is connected and approved for changes.' :
      'Tap a day to see its plans. Review event changes before saving.';

    const nextGrid = JSON.stringify([month, selected, localDate(new Date()), events.map(event => [event.id, event.start, event.end, event.all_day])]);
    if (nextGrid !== gridSignature) {
      const first = dateAtNoon(month + '-01'), offset = (first.getDay() + 6) % 7;
      const cells = Math.ceil((offset + daysInMonth()) / 7) * 7;
      $('calendar-grid').innerHTML = Array.from({length:cells}, (_, index) => {
        const number = index - offset + 1;
        if (number < 1 || number > daysInMonth()) return '<span class="calendar-blank" aria-hidden="true"></span>';
        const key = month + '-' + String(number).padStart(2, '0'), count = events.filter(event => onDay(event, key)).length;
        return `<button type="button" class="calendar-date${key === selected ? ' selected' : ''}${key === localDate(new Date()) ? ' today' : ''}" data-calendar-date="${key}" aria-pressed="${key === selected}"${key === localDate(new Date()) ? ' aria-current="date"' : ''} aria-label="${esc(fullDate(key))}${count ? `, ${count} event${count === 1 ? '' : 's'}` : ''}"><span>${number}</span><small>${count ? '•'.repeat(Math.min(count, 3)) : '&nbsp;'}</small></button>`;
      }).join('');
      gridSignature = nextGrid;
    }
    const days = view === 'month' ? [selected] : Array.from({length:daysInMonth()}, (_, index) => month + '-' + String(index + 1).padStart(2, '0'));
    const nextAgenda = JSON.stringify([days, events, unavailable, sources.length, state?.status, preferences.clock24]);
    if (nextAgenda !== agendaSignature) {
      let html = '';
      for (const day of days) {
        const items = events.filter(event => onDay(event, day));
        if (!items.length) continue;
        if (view === 'agenda') html += `<h3 class="calendar-list-date">${esc(dateAtNoon(day).toLocaleDateString(undefined, {weekday:'short', month:'short', day:'numeric'}))}</h3>`;
        html += items.map(event => eventMarkup(event, day, sources)).join('');
      }
      $('calendar-day-events').innerHTML = html || `<div class="calendar-empty">${icon('calendar')}<h3>${!sources.length ? 'Your plans belong here.' : unavailable ? 'Waiting for your calendar.' : 'A little breathing room.'}</h3><p class="soft">${!sources.length ? 'Shared calendars will appear here once connected.' : unavailable ? 'Events will return when the connection recovers.' : state?.status === 'partial' ? 'No events returned from the calendars we could reach.' : view === 'month' ? 'Nothing scheduled for this day.' : 'Nothing scheduled for this month.'}</p></div>`;
      agendaSignature = nextAgenda;
    }
  }
  extensions.push(renderCalendar);
  $('calendar-previous').onclick = () => changeMonth(-1);
  $('calendar-next').onclick = () => changeMonth(1);
  $('calendar-today').onclick = () => {
    selected = localDate(new Date()); month = selected.slice(0, 7);
    delete data.calendarAgenda; updateEndpoint(); renderCalendar(); void refresh();
  };
  $('calendar-filter').onchange = event => {filter = event.target.value; renderCalendar();};
  $('calendar-grid').onclick = event => {
    const key = event.target.closest('[data-calendar-date]')?.dataset.calendarDate;
    if (!key) return; selected = key; renderCalendar();
    $('calendar-grid').querySelector(`[data-calendar-date="${key}"]`)?.focus({preventScroll:true});
  };
  $('calendar-day-events').onclick = event => {
    const id = event.target.closest('[data-calendar-event]')?.dataset.calendarEvent;
    const item = fresh('calendarAgenda') && data.calendarAgenda.events.find(entry => entry.id === id);
    if (item) showCalendarDetails(item);
  };
  screen.querySelectorAll('[data-calendar-view]').forEach(button => button.onclick = () => {
    view = button.dataset.calendarView; screen.classList.toggle('calendar-agenda-view', view === 'agenda');
    screen.querySelectorAll('[data-calendar-view]').forEach(control => {control.classList.toggle('selected', control === button); control.setAttribute('aria-pressed', String(control === button));});
    renderCalendar();
  });
  $('calendar-page-new').onclick = () => openCalendarEvent(null, {date:selected, calendar:filter});
  $('calendar-connect').onclick = () => {if(window.EchoSettings.open('home','google-calendar-card'))$('google-load').click();};
  $('calendar-sources').onclick = () => {if(window.EchoSettings.open('home',sourceCard))$('source-load').click();};
  $('calendar-personal').onclick = () => $('member-google-button').click();
  document.addEventListener('echo:page', event => {if (event.detail === 'calendar') renderCalendar();});
})();

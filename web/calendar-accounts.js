/* Browser-native Google Calendar linking. No Google tokens or passcodes are stored here. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const client = [...crypto.getRandomValues(new Uint8Array(32))].map(value => value.toString(16).padStart(2, '0')).join('');
  let mode = '', state = null, flow = null, busy = false;
  const base = () => mode === 'private' ? '/v1/member/calendar/google' : '/v1/calendar/google';
  const status = message => { $('calendar-account-status').textContent = message; };
  async function api(path, method = 'GET', body) {
    const response = await fetch(path, {method, credentials: 'same-origin', cache: 'no-store',
      headers: {'Content-Type': 'application/json', 'X-Echo-Request': '1'},
      body: body === undefined ? undefined : JSON.stringify(body)});
    const result = await response.json();
    if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : 'Echo could not complete this request.');
    return result;
  }
  function row(label, note, controls) {
    const item = document.createElement('div'); item.className = 'calendar-account-row';
    const name = document.createElement('strong'); name.textContent = label;
    const description = document.createElement('small'); description.textContent = note;
    const actions = document.createElement('div'); actions.className = 'actions';
    for (const [caption, callback] of controls) {
      const button = document.createElement('button'); button.type = 'button';
      button.className = 'secondary'; button.textContent = caption; button.onclick = callback; actions.append(button);
    }
    item.append(name, description, actions); return item;
  }
  async function load() {
    state = await api(base());
    if (mode === 'private') {
      const accounts = $('calendar-private-accounts'); accounts.replaceChildren();
      for (const account of state.accounts) accounts.append(row(account.label,
        `${account.calendar_count} calendars · private, read-only`, [
          ['Refresh calendars', () => accountAction(account.id, false)],
          ['Disconnect', () => accountAction(account.id, true)]]));
      const choices = $('calendar-private-choices'); choices.replaceChildren();
      for (const calendar of state.calendars) {
        const label = document.createElement('label'); label.className = 'calendar-private-choice';
        const check = document.createElement('input'); check.type = 'checkbox'; check.value = calendar.entity_id;
        check.checked = calendar.selected;
        const copy = document.createElement('span'); copy.textContent = `${calendar.name} · ${calendar.account_label}`;
        label.append(check, copy); choices.append(label);
      }
      if (!state.calendars.length) choices.textContent = 'Connect an account to see its calendars.';
      $('calendar-private-connect').querySelector('button').disabled = !state.enabled || !state.configured || state.needs_reconnect;
      $('calendar-private-selection').querySelector('button').disabled = !state.calendars.length || state.needs_reconnect;
      status(!state.configured ? 'The owner must complete the one-time Google OAuth setup first.' :
        state.needs_reconnect ? 'The owner changed Google setup. Disconnect and reconnect this private account.' :
        'Choose only the calendars you want in your private agenda.');
    } else {
      $('calendar-owner-id').value = state.client_id;
      $('calendar-owner-redirect').value = state.redirect_uri || location.origin + '/v1/calendar/google/callback';
      $('calendar-owner-secret').value = '';
      $('calendar-owner-setup').open = !state.secret_saved;
      $('calendar-owner-connect').querySelector('button').disabled = !state.enabled || !state.secret_saved;
      const accounts = $('calendar-owner-accounts'); accounts.replaceChildren();
      for (const account of state.accounts) accounts.append(row(account.label,
        `${account.calendar_count} calendars · not shared unless explicitly selected`, [
          ['Refresh calendars', () => accountAction(account.id, false)],
          ['Disconnect', () => accountAction(account.id, true)]]));
      status(!state.enabled ? 'Google connections are disabled on this host.' :
        state.secret_saved ? 'Google setup is ready. Personal profiles can connect privately.' :
        'Complete the one-time Google OAuth setup, then connect an account.');
    }
  }
  async function boot() {
    try {
      const session = await api('/v1/display/session');
      mode = session.member ? 'private' : 'owner';
      $('calendar-account-private').hidden = mode !== 'private';
      $('calendar-account-login').hidden = mode !== 'owner';
      $('calendar-account-owner').hidden = mode !== 'owner';
      if (mode === 'private') $('calendar-account-person').textContent = `${session.member.name}’s private calendars`;
      else {
        const available = await api('/v1/members/available');
        const chooser = $('calendar-account-member'); chooser.replaceChildren();
        for (const member of available.items) {
          const option = document.createElement('option'); option.value = member.id;
          option.textContent = member.name; chooser.append(option);
        }
        $('calendar-account-no-members').hidden = !!available.items.length;
        $('calendar-account-login-form').querySelector('button').disabled = !available.items.length;
      }
      await load();
    } catch (error) { status(error.message + ' Open Echo from its launcher if this browser is locked.'); }
  }
  function clearFlow() {
    flow = null; $('calendar-account-flow').hidden = true;
    $('calendar-flow-open').removeAttribute('href'); $('calendar-flow-finish').hidden = true;
  }
  function showFlow(value) {
    const messages = {waiting: 'Approve read-only Calendar access in Google, then return here.',
      exchanging: 'Receiving Google’s response…', approved: 'Approved. Finish connecting in this Echo tab.',
      declined: 'Google sign-in was declined. Cancel and try again.',
      failed: 'Google could not complete sign-in. Cancel and try again.'};
    $('calendar-flow-status').textContent = messages[value] || 'Checking Google sign-in…';
    $('calendar-flow-finish').hidden = value !== 'approved';
    $('calendar-flow-open').hidden = value !== 'waiting';
  }
  async function begin(label) {
    if (busy || flow) return;
    busy = true;
    try {
      const result = await api(base() + '/flows', 'POST',
        mode === 'private' ? {label, client} : {label, client, write_access: false});
      const url = new URL(result.url);
      if (url.origin !== 'https://accounts.google.com' || url.pathname !== '/o/oauth2/v2/auth')
        throw Error('Echo returned an unexpected Google sign-in address.');
      flow = result; $('calendar-flow-open').href = result.url;
      $('calendar-account-flow').hidden = false; showFlow('waiting');
      $('calendar-account-flow').scrollIntoView({block: 'start'});
    } catch (error) { status(error.message); }
    finally { busy = false; }
  }
  async function poll() {
    if (!flow || busy || document.hidden) return;
    const current = flow;
    try {
      const result = await api(base() + '/flows/' + current.id + '?client=' + client);
      if (flow === current) showFlow(result.status);
    } catch (error) { if (flow === current) { clearFlow(); status(error.message); } }
  }
  async function finish() {
    if (!flow || busy) return;
    busy = true;
    try {
      const result = await api(base() + '/flows/' + flow.id + '/finish', 'POST', {client});
      clearFlow();
      try { await api(base() + '/accounts/' + result.id + '/sync', 'POST', {}); }
      catch { status('Connected, but the calendar list could not load. Use Refresh calendars.'); }
      await load();
      status(mode === 'private' ? 'Connected privately. Select calendars and save your agenda.' :
        'Connected. Nothing is shared until you choose calendars on the Deck.');
    } catch (error) { $('calendar-flow-status').textContent = error.message; }
    finally { busy = false; }
  }
  async function accountAction(id, disconnect) {
    if (busy || flow) return;
    if (disconnect && !confirm('Disconnect this Google account from Echo?')) return;
    busy = true;
    try {
      await api(base() + '/accounts/' + id + (disconnect ? '' : '/sync'), disconnect ? 'DELETE' : 'POST', {});
      await load();
    } catch (error) { status(error.message); }
    finally { busy = false; }
  }
  $('calendar-account-login-form').onsubmit = async event => {
    event.preventDefault(); if (busy) return;
    busy = true;
    const passcode = $('calendar-account-passcode').value;
    $('calendar-account-passcode').value = '';
    try {
      await api('/v1/member/session', 'POST', {member: $('calendar-account-member').value, passcode});
      location.reload();
    } catch (error) { status(error.message); busy = false; }
  };
  $('calendar-account-lock').onclick = async () => {
    try { await api('/v1/member/session', 'DELETE'); location.reload(); }
    catch (error) { status(error.message); }
  };
  $('calendar-owner-config').onsubmit = async event => {
    event.preventDefault(); if (busy) return;
    busy = true;
    try {
      await api('/v1/calendar/google', 'PUT', {revision: state.revision,
        client_id: $('calendar-owner-id').value.trim(), client_secret: $('calendar-owner-secret').value,
        redirect_uri: $('calendar-owner-redirect').value.trim()});
      await load(); status('Google OAuth setup saved.');
    } catch (error) { status(error.message); }
    finally { busy = false; }
  };
  $('calendar-private-connect').onsubmit = event => { event.preventDefault(); void begin($('calendar-private-label').value); };
  $('calendar-owner-connect').onsubmit = event => { event.preventDefault(); void begin($('calendar-owner-label').value); };
  $('calendar-private-selection').onsubmit = async event => {
    event.preventDefault(); if (busy || flow) return;
    busy = true;
    const calendars = [...$('calendar-private-choices').querySelectorAll('input:checked')].map(input => input.value);
    try { await api(base() + '/selection', 'PUT', {revision: state.revision, calendars}); await load(); status('Private calendar selection saved.'); }
    catch (error) { status(error.message); }
    finally { busy = false; }
  };
  $('calendar-flow-finish').onclick = () => void finish();
  $('calendar-flow-cancel').onclick = async () => {
    const current = flow; clearFlow();
    if (current) try { await api(base() + '/flows/' + current.id, 'DELETE', {client}); }
    catch (error) { status(error.message); }
  };
  setInterval(() => void poll(), 3000);
  void boot();
})();

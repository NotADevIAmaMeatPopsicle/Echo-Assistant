// Run against tools/preview_smart_display.py only, with playwright-cli run-code --filename.
async (page) => {
  const base = await page.evaluate(() => location.origin);
  const health = await (await page.request.get(base + '/health')).json();
  if (!health.display_demo) throw new Error('Calendar UI checks require the synthetic preview.');
  const assert = (value, message) => {if (!value) throw new Error(message);};
  const checks = [];
  await page.goto(base + '/display#calendar');
  await page.waitForFunction(() => document.querySelector('#calendar-day-events .calendar-entry'));
  const month = (await page.locator('[data-calendar-date]').first().getAttribute('data-calendar-date')).slice(0, 7);
  const source = await (await page.request.get(base + '/v1/display/sources')).json();
  const household = source.items.find(item => item.kind === 'calendar');
  const work = {...household, entity_id:'calendar.work_demo', name:'Work · sample', writable:false, editable:false, deletable:false};
  const sources = {...source, items:[household, work]};
  let mode = 'events';
  await page.route('**/v1/display/sources', route => route.fulfill({json:mode === 'empty' ? {...sources, items:[]} : sources}));
  await page.route('**/v1/display/agenda?*', async route => {
    const requested = route.request().url().match(/[?&]start=([^&]+)/)[1].slice(0, 7);
    const event = (id, calendar, title, start, end, all_day) => ({id, calendar:calendar.entity_id, calendar_name:calendar.name, title, start, end, all_day, location:''});
    const events = requested === month && mode !== 'empty' ? [
      event('sample-all-day', household, 'Two-day visit', month+'-10', month+'-12', true),
      event('sample-midnight', household, 'Ends at midnight', month+'-11T23:00:00-04:00', month+'-12T00:00:00-04:00', false),
      event('sample-work', work, 'Work planning', month+'-11', month+'-12', true)
    ] : [];
    await route.fulfill({json:{status:'available', events, unavailable:[]}});
  });
  await page.reload();
  await page.waitForFunction(() => document.querySelector('#calendar-filter').options.length === 3);
  await page.locator(`[data-calendar-date="${month}-11"]`).click();
  await page.waitForFunction(() => document.querySelectorAll('#calendar-day-events .calendar-entry').length === 3);
  await page.locator(`[data-calendar-date="${month}-12"]`).click();
  assert(await page.locator('#calendar-day-events .calendar-entry').count() === 0, 'Exclusive all-day and midnight ends must not spill into the next day.');
  checks.push('exclusive event ends');
  await page.locator(`[data-calendar-date="${month}-11"]`).click();
  await page.locator('#calendar-filter').selectOption('calendar.work_demo');
  assert(await page.locator('#calendar-day-events .calendar-entry').count() === 1, 'Calendar filtering failed.');
  await page.locator('#calendar-day-events .calendar-entry').click();
  assert(await page.locator('#calendar-details-dialog').isVisible(), 'Event details did not open.');
  await page.locator('#calendar-details-close').click();
  checks.push('calendar filtering and shared details');
  await page.locator('#calendar-filter').selectOption(household.entity_id);
  await page.locator(`[data-calendar-date="${month}-13"]`).click();
  await page.locator('#calendar-page-new').click();
  assert((await page.locator('#event-start').inputValue()).startsWith(month+'-13T'), 'New event must use the selected day.');
  assert(await page.locator('#event-calendar').inputValue() === household.entity_id, 'New event must use the selected writable calendar.');
  await page.locator('#calendar-event-cancel').click();
  assert(await page.locator('#calendar-page-new').evaluate(button => button === document.activeElement), 'Closing the event form must restore focus.');
  checks.push('selected date, calendar and form focus');
  await page.locator('[data-calendar-view="agenda"]').click();
  assert(await page.locator('#calendar-next').isVisible(), 'Agenda view lost month navigation.');
  assert((await page.locator('#calendar-day-events').innerText()).includes('Two-day visit'), 'Month agenda omitted events.');
  await page.locator('#calendar-next').click();
  await page.waitForFunction(() => !document.querySelector('#calendar-day-events .calendar-entry'));
  await page.locator('#calendar-today').click();
  await page.locator('[data-calendar-view="month"]').click();
  checks.push('agenda and month navigation');
  await page.locator('#calendar-connect').click();
  await page.waitForFunction(() => document.querySelector('#google-panel').hidden === false);
  assert(await page.locator('#google-setup').getAttribute('open') !== null, 'Unconfigured Google shortcut should open setup.');
  checks.push('Google setup shortcut');
  await page.locator('#navigation [data-page="calendar"]').click();
  await page.setViewportSize({width:390, height:844});
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Phone layout overflows horizontally.');
  await page.screenshot({path:'output/playwright/calendar-phone.png'});
  checks.push('phone layout');
  await page.setViewportSize({width:1024, height:600});
  mode = 'empty'; await page.reload();
  await page.waitForFunction(() => document.querySelector('#calendar-page-status').textContent.includes('Connect a calendar'));
  assert(await page.locator('#calendar-page-new').isDisabled(), 'Unconfigured calendar must not offer event submission.');
  await page.screenshot({path:'output/playwright/calendar-empty.png'});
  checks.push('honest unconfigured state');
  mode = 'events';
  await page.route('**/v1/display/session', route => route.fulfill({json:{role:'display', receiver_id:'sample-guest', profile_revision:1, profile:{mode:'guest', name:'Guest', conversation:false, home_voice:false}}}));
  await page.reload();
  await page.waitForFunction(() => document.body.classList.contains('guest-display'));
  assert(page.url().endsWith('#calendar'), 'Guest calendar route should remain available.');
  assert(await page.locator('#calendar-page-new').isHidden() && await page.locator('#calendar-connect').isHidden(), 'Guest calendar must hide owner/write controls.');
  checks.push('guest navigation and read-only controls');
  await page.unroute('**/v1/display/session');
  await page.unroute('**/v1/display/sources');
  await page.unroute('**/v1/display/agenda?*');
  await page.goto(base + '/display#calendar');
  await page.waitForFunction(() => document.querySelector('#calendar-day-events .calendar-entry'));
  await page.screenshot({path:'output/playwright/calendar-deck.png'});
  console.log(JSON.stringify({passed:checks, live_calendar_writes:0}));
}

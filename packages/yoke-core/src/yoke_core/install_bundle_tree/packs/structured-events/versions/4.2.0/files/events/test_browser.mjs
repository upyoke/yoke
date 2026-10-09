import test from 'node:test';
import assert from 'node:assert/strict';
import { createAttributionHandler, createCollector } from './api-route.ts';
import rules from './attribution_rules.json' with { type: 'json' };
import { sanitizeUrl, isBot } from './events_attribution.ts';

const windowEvents = new EventTarget();
const documentEvents = new EventTarget();
let location = new URL('https://app.example.com/?token=private&utm_source=chatgpt.com');
globalThis.window = Object.assign(windowEvents, {
  get location() { return location; }, innerWidth: 1200,
});
Object.defineProperty(window, 'location', { get: () => location });
globalThis.document = Object.assign(documentEvents, { title: 'Page', referrer: '', visibilityState: 'visible' });
Object.defineProperty(globalThis, 'navigator', { value: { userAgent: 'HeadlessChrome' }, configurable: true });
globalThis.history = {
  pushState(_state, _title, url) { if (url) location = new URL(url, location); },
  replaceState(_state, _title, url) { if (url) location = new URL(url, location); },
};
let timerId = 0;
const timers = new Map();
globalThis.setTimeout = (fn, delay) => { timers.set(++timerId, { fn, delay }); return timerId; };
globalThis.clearTimeout = id => timers.delete(id);
const waitFor = async (condition) => {
  const deadline = performance.now() + 5000;
  while (!await condition()) {
    assert.ok(performance.now() < deadline, 'browser_contract_timeout: expected asynchronous work to complete');
    await new Promise(setImmediate);
  }
};

const { configureEvents, emitEvent, flushEvents, getStoredAttribution } = await import('./events.ts');
const { startPageViews } = await import('./events_navigation.ts');
const base = {
  publishableKey: 'public', allowedOrigins: ['https://app.example.com'],
  rateLimit: async () => 0, writeEvents: async () => {},
};
const attribution = await createAttributionHandler({ ...base, signingSecret: 's'.repeat(32), siteDomain: 'example.com' });
let serverCookie = '';
const batches = [];
let mode = 'success';
let captureCount = 0;
let releaseBatch;
globalThis.fetch = async (url, options) => {
  if (url.endsWith('/attribution')) {
    captureCount++;
    // Exercise completion waits beyond the old fixed event-loop turn budget.
    for (let i = 0; i < 40; i++) await new Promise(setImmediate);
    const response = await attribution(new Request('https://app.example.com' + url, {
      ...options, headers: { ...options.headers, Origin: 'https://app.example.com', Cookie: serverCookie },
    }));
    if (response.headers.has('Set-Cookie')) serverCookie = response.headers.get('Set-Cookie').split(';')[0];
    return response;
  }
  batches.push(JSON.parse(options.body));
  assert.equal(options.headers['X-Events-Key'], 'public');
  assert.equal(options.keepalive, true);
  if (mode === 'network') throw new Error('offline');
  if (mode === '429') return new Response('', { status: 429, headers: { 'Retry-After': '30' } });
  if (['400', '401', '403', '503'].includes(mode)) return Response.json({ error: 'publishable_key_invalid', recovery: 'configure the current public key' }, { status: Number(mode) });
  if (mode === 'pending') await new Promise(resolve => { releaseBatch = resolve; });
  return Response.json({ accepted: batches.at(-1).events.length });
};

test('first load collects with no consent step: server persistence, SPA views and failures', async () => {
  configureEvents({ publishableKey: 'public' });
  const cleanup = startPageViews();
  await waitFor(async () => { await flushEvents(); return batches.length === 1; });
  const first = getStoredAttribution();
  assert.equal(first.first_touch.acquisition_channel, 'ai_assistant');
  assert.ok(first.visitor_id);
  await flushEvents();
  assert.equal(batches[0].events.length, 1);
  assert.equal(batches[0].events[0].visitor_id, first.visitor_id);
  assert.ok(!batches[0].events[0].page_url.includes('token'));
  assert.equal(batches[0].events[0].is_bot, true);

  // A view follows the path: filter and app rewrites that only change the query are not pages.
  history.pushState({}, '', '/orders');
  history.replaceState({}, '', '/orders?selection=all');
  history.pushState({}, '', '/orders?tab=all');
  location = new URL('https://app.example.com/back');
  window.dispatchEvent(new Event('popstate'));
  history.replaceState({}, '', '/back'); // State-only update is not another page.
  await waitFor(async () => {
    await flushEvents();
    return batches.slice(1).flatMap(batch => batch.events).length === 2;
  });
  const views = batches.slice(1).flatMap(batch => batch.events);
  assert.deepEqual(views.map(e => e.page_path), ['/orders', '/back']);
  assert.equal(views[0].referrer, 'https://app.example.com/?utm_source=chatgpt.com');
  assert.ok(views.every(e => e.visitor_id === first.visitor_id));

  const realNow = Date.now;
  let now = realNow();
  Date.now = () => now;
  mode = 'network';
  const event = emitEvent({ name: 'Clicked', kind: 'analytics', eventType: 'interaction' });
  await flushEvents();
  const calls = batches.length;
  await flushEvents();
  assert.equal(batches.length, calls);
  now += 6000;
  mode = '429';
  await flushEvents();
  now += 10000;
  await flushEvents();
  assert.equal(batches.length, calls + 1);
  now += 21000;
  mode = 'success';
  await flushEvents();
  assert.equal(batches.at(-1).events[0].event_id, event.event_id);
  assert.deepEqual(batches.at(-1), batches.at(-2));
  Date.now = realNow;
  mode = 'pending';
  emitEvent({ name: 'Clicked', kind: 'analytics', eventType: 'interaction' });
  const sending = flushEvents();
  const overlapping = flushEvents();
  const before = batches.length;
  emitEvent({ name: 'Clicked', kind: 'analytics', eventType: 'interaction' });
  releaseBatch();
  await Promise.all([sending, overlapping]);
  assert.equal(batches.length, before); // One transport for the in-flight batch.
  mode = 'success';
  document.visibilityState = 'hidden';
  document.dispatchEvent(new Event('visibilitychange'));
  await waitFor(() => batches.length === before + 1);
  assert.equal(batches.length, before + 1);
  cleanup();
  assert.equal(captureCount, 3); // One serial capture per distinct page view.
  assert.ok(serverCookie.startsWith('__Host-events_attribution='));
  assert.equal(timers.size, 0);
});

test('two separately bundled trackers on one document emit one view per navigation', async () => {
  // A query-suffixed import is a second module instance, as a second bundle would be.
  const second = await import('./events_navigation.ts?second-bundle');
  const warnings = [], originalWarn = console.warn;
  console.warn = (...args) => warnings.push(args.join(' '));
  mode = 'success';
  const start = batches.length;
  const host = startPageViews();
  const embedded = second.startPageViews();
  console.warn = originalWarn;
  assert.match(warnings[0], /page_views_already_started/);
  history.pushState({}, '', '/shared');
  const views = () => batches.slice(start).flatMap(batch => batch.events).filter(e => e.event_type === 'page_view');
  await waitFor(async () => { await flushEvents(); return views().length === 2; });
  assert.deepEqual(views().map(e => e.page_path), ['/back', '/shared']);
  embedded();
  host();
  const replacement = second.startPageViews(); // Cleanup releases the document marker.
  replacement();
});

test('device-login codes never reach a stored URL field', async () => {
  const start = batches.length;
  location = new URL('https://app.example.com/machine-approval/RXZ2-AGEE?user_code=RXZ2-AGEE&tab=1');
  document.referrer = 'https://app.example.com/device?user_code=NE8L-CUWF';
  const stop = startPageViews();
  history.pushState({}, '', '/machine-approval/ZREV-7CLG');
  history.pushState({}, '', '/done');
  const views = () => batches.slice(start).flatMap(batch => batch.events).filter(e => e.event_type === 'page_view');
  await waitFor(async () => { await flushEvents(); return views().length === 3; });
  stop();
  document.referrer = '';
  assert.deepEqual(views().map(e => e.page_path), ['/machine-approval/redacted', '/machine-approval/redacted', '/done']);
  assert.equal(views()[0].page_url, 'https://app.example.com/machine-approval/redacted?tab=1');
  assert.equal(views()[2].referrer, 'https://app.example.com/machine-approval/redacted');
  const stored = JSON.stringify(views().map(e => [e.page_url, e.page_path, e.referrer]));
  assert.doesNotMatch(stored, /user_code|RXZ2|NE8L|ZREV/);
});

test('anonymous collector rejects wrong key/origin, honors rate limits and sanitizes input', async () => {
  const writes = [];
  let delay = 0;
  const handler = createCollector({ ...base, rateLimit: async () => delay, writeEvents: async events => { writes.push(events); } });
  const event = { event_id: crypto.randomUUID(), event_name: 'PageViewed', event_kind: 'analytics',
    event_type: 'page_view', event_time: new Date().toISOString(), session_id: 'session', source_type: 'frontend',
    page_url: 'https://app.example.com/?token=private&tab=all', page_path: '/Machine-Approval/GAXK-3XPY',
    referrer: 'https://app.example.com/machine-approval/GAXK-3XPY?user_code=GAXK-3XPY', actor_id: 999, org_id: 'forged', is_bot: false };
  const request = (key = 'public', origin = 'https://app.example.com', events = [event]) => new Request('https://app.example.com/api/events', {
    method: 'POST', headers: { Origin: origin, 'X-Events-Key': key, 'Content-Type': 'application/json', 'User-Agent': 'HeadlessChrome' }, body: JSON.stringify({ events }),
  });
  assert.equal((await handler(request('wrong'))).status, 401);
  assert.equal((await handler(request('public', 'https://evil.com'))).status, 403);
  delay = 2000;
  const limited = await handler(request());
  assert.equal(limited.status, 429);
  assert.equal(limited.headers.get('Retry-After'), '2');
  delay = 0;
  assert.equal((await handler(request())).status, 200); // No bearer credential.
  assert.equal(writes.length, 1);
  assert.equal(writes[0][0].page_url, 'https://app.example.com/?tab=all');
  assert.equal(writes[0][0].page_path, '/Machine-Approval/redacted');
  assert.equal(writes[0][0].referrer, 'https://app.example.com/machine-approval/redacted');
  assert.equal(writes[0][0].is_bot, true);
  assert.ok(!('actor_id' in writes[0][0]) && !('org_id' in writes[0][0]));
  assert.equal((await handler(request('public', 'https://app.example.com', [null]))).status, 400);
  assert.equal(sanitizeUrl('https://user:password@example.com/?TOKEN=x&tab=all#secret'), 'https://example.com/?tab=all');
  assert.equal(isBot('Mozilla/5.0'), false);
});


test('server failures retry while permanent refusals drop with a named recovery', async () => {
  const warn = console.warn, warnings = [];
  console.warn = (...values) => warnings.push(values.join(' '));
  const realNow = Date.now;
  let now = realNow();
  Date.now = () => now;
  try {
    mode = '503';
    const event = emitEvent({ name: 'Clicked', kind: 'analytics', eventType: 'interaction' });
    await flushEvents();
    const before = batches.length;
    await flushEvents();
    assert.equal(batches.length, before);
    now += 6000;
    mode = '401';
    await flushEvents();
    assert.equal(batches.at(-1).events[0].event_id, event.event_id);
    for (const status of ['400', '403']) {
      mode = status;
      emitEvent({ name: 'Clicked', kind: 'analytics', eventType: 'interaction' });
      await flushEvents();
    }
    const dropped = batches.length;
    now += 60000;
    await flushEvents();
    assert.equal(batches.length, dropped);
    assert.equal(warnings.filter(value => value.includes('batch_refused: publishable_key_invalid; configure the current public key')).length, 3);
  } finally {
    console.warn = warn; Date.now = realNow; mode = 'success';
  }
});

test('queue capacity bounds pending events during a transport outage', async () => {
  const warn = console.warn, warnings = [];
  console.warn = (...values) => warnings.push(values.join(' '));
  try {
    mode = 'pending';
    const before = batches.length;
    const total = rules.limits.queue_events + 100;
    for (let i = 0; i < total; i++) emitEvent({ name: 'Clicked', kind: 'analytics', eventType: 'interaction' });
    assert.equal(batches.length, before + 1);
    const inFlight = batches.at(-1).events.length;
    const sending = flushEvents();
    releaseBatch();
    await sending;
    mode = 'success';
    // One bounded batch per flush; drain until no more transport is scheduled.
    for (let i = 0; i < rules.limits.queue_events; i++) {
      const count = batches.length;
      await flushEvents();
      if (count === batches.length) break;
    }
    const delivered = batches.slice(before).flatMap(batch => batch.events);
    assert.equal(delivered.length, inFlight + rules.limits.queue_events);
    assert.equal(new Set(delivered.map(event => event.event_id)).size, delivered.length);
    assert.ok(warnings.some(value => value.includes('batch_queue_full')));
  } finally {
    console.warn = warn; mode = 'success';
  }
});

test('rotated or invalid attribution cookies recover through the capture API', async () => {
  const handler = await createAttributionHandler({ ...base, signingSecret: 't'.repeat(32), siteDomain: 'WWW.EXAMPLE.COM.' });
  const request = cookie => new Request('https://app.example.com/api/events/attribution', {
    method: 'POST', headers: { Origin: 'https://app.example.com', 'X-Events-Key': 'public', 'Content-Type': 'application/json', Cookie: cookie },
    body: JSON.stringify({ url: 'https://APP.EXAMPLE.COM./?fbclid=paid', referrer: '' }),
  });
  const oldResponse = await attribution(request(''));
  const original = await oldResponse.json();
  for (const cookie of [oldResponse.headers.get('Set-Cookie'), '__Host-events_attribution=bad.bad']) {
    const response = await handler(request(cookie));
    assert.equal(response.status, 200);
    assert.ok(response.headers.get('Set-Cookie').includes('HttpOnly'));
    const record = await response.json();
    assert.notEqual(record.visitor_id, original.visitor_id);
    assert.equal(record.first_touch.acquisition_channel, 'paid_social');
  }
});

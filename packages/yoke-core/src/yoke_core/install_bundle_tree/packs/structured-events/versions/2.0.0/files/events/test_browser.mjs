import test from 'node:test';
import assert from 'node:assert/strict';
import { createAttributionHandler, createCollector } from './api-route.ts';
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
const tick = async () => { for (let i = 0; i < 20; i++) await new Promise(setImmediate); };

const { configureEvents, setConsent, emitEvent, flushEvents, getStoredAttribution } = await import('./events.ts');
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
let failDelete = false;
globalThis.fetch = async (url, options) => {
  if (url.endsWith('/attribution')) {
    captureCount++;
    if (options.method === 'DELETE' && failDelete) return new Response('', { status: 503 });
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
  if (mode === 'pending') await new Promise(resolve => { releaseBatch = resolve; });
  return Response.json({ accepted: batches.at(-1).events.length });
};

test('consent, server persistence, SPA views, failures, and revocation', async () => {
  configureEvents({ publishableKey: 'public' });
  const cleanup = startPageViews();
  assert.equal(emitEvent({ name: 'PageViewed', kind: 'analytics', eventType: 'page_view' }), null);
  await tick();
  assert.equal(captureCount, 0);
  assert.equal(serverCookie, '');
  await setConsent(true);
  await tick();
  const first = getStoredAttribution();
  assert.equal(first.first_touch.acquisition_channel, 'ai_assistant');
  assert.ok(first.visitor_id);
  await flushEvents();
  assert.equal(batches[0].events.length, 1);
  assert.equal(batches[0].events[0].visitor_id, first.visitor_id);
  assert.ok(!batches[0].events[0].page_url.includes('token'));
  assert.equal(batches[0].events[0].is_bot, true);

  history.pushState({}, '', '/orders');
  history.replaceState({}, '', '/orders?tab=all');
  location = new URL('https://app.example.com/back');
  window.dispatchEvent(new Event('popstate'));
  history.replaceState({}, '', '/back'); // State-only update is not another page.
  await tick();
  await flushEvents();
  const views = batches[1].events;
  assert.deepEqual(views.map(e => e.page_path), ['/orders', '/orders', '/back']);
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
  await tick();
  assert.equal(batches.length, before + 1);
  cleanup();

  mode = 'network';
  emitEvent({ name: 'Clicked', kind: 'analytics', eventType: 'interaction' });
  await flushEvents();
  failDelete = true;
  await setConsent(false);
  assert.notEqual(serverCookie, '__Host-events_attribution=');
  failDelete = false;
  await setConsent(false); // A failed delete remains retryable while denied.
  const after = batches.length;
  await flushEvents();
  assert.equal(batches.length, after);
  assert.equal(getStoredAttribution(), null);
  assert.equal(serverCookie, '__Host-events_attribution=');
  assert.equal(timers.size, 0);
});

test('anonymous collector rejects wrong key/origin, honors rate limits and sanitizes input', async () => {
  const writes = [];
  let delay = 0;
  const handler = createCollector({ ...base, rateLimit: async () => delay, writeEvents: async events => { writes.push(events); } });
  const event = { event_id: crypto.randomUUID(), event_name: 'PageViewed', event_kind: 'analytics',
    event_type: 'page_view', event_time: new Date().toISOString(), session_id: 'session', source_type: 'frontend',
    page_url: 'https://app.example.com/?token=private&tab=all', actor_id: 999, org_id: 'forged', is_bot: false };
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
  assert.equal(writes[0][0].is_bot, true);
  assert.ok(!('actor_id' in writes[0][0]) && !('org_id' in writes[0][0]));
  assert.equal((await handler(request('public', 'https://app.example.com', [null]))).status, 400);
  assert.equal(sanitizeUrl('https://user:password@example.com/?TOKEN=x&tab=all#secret'), 'https://example.com/?tab=all');
  assert.equal(isBot('Mozilla/5.0'), false);
});

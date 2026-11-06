import assert from 'node:assert/strict';
import { createCollector } from './api-route.ts';
import { deviceProps } from './events_device.ts';
import { getDeviceProps } from './events_props.ts';

const MAC_CHROME = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36';
const ANDROID = 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36';
export async function checkCollectorDeviceContext(base) {
  const cases = [
    [{ 'User-Agent': MAC_CHROME }, ['Chrome', 'macOS', 'desktop']],
    [{ 'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1' }, ['Safari', 'iOS', 'mobile']],
    [{ 'User-Agent': 'Mozilla/5.0 (iPad; CPU OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1' }, ['Safari', 'iOS', 'tablet']],
    [{ 'User-Agent': ANDROID, 'Sec-CH-UA-Mobile': '?1', 'Sec-CH-UA-Platform': '"Android"' }, ['Chrome', 'Android', 'mobile']],
    [{ 'User-Agent': ANDROID, 'Sec-CH-UA-Mobile': '?0', 'Sec-CH-UA-Platform': '"Android"' }, ['Chrome', 'Android', 'tablet']],
    [{ 'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Claude/1.0.211 Chrome/138.0.7204.251 Electron/37.6.0 Safari/537.36' }, ['Electron', 'macOS', 'desktop']],
  ];
  for (const [headers, expected] of cases) {
    const props = deviceProps(new Headers(headers));
    assert.deepEqual([props.browser, props.os, props.device_type], expected);
    assert.ok(props.browser_version);
  }
  assert.deepEqual(deviceProps(new Headers()), { is_bot: false, browser: null, browser_version: null, os: null, device_type: null });
  assert.ok(!('device_type' in getDeviceProps()));
  const writes = [];
  const handler = createCollector({ ...base, rateLimit: async () => 0, writeEvents: async events => { writes.push(events); } });
  const event = { event_id: crypto.randomUUID(), event_name: 'PageViewed', event_kind: 'analytics', event_type: 'page_view',
    event_time: new Date().toISOString(), session_id: 'session', source_type: 'frontend', device_type: 'mobile', browser: 'forged' };
  const response = await handler(new Request('https://app.example.com/api/events', { method: 'POST', body: JSON.stringify({ events: [event] }),
    headers: { Origin: 'https://app.example.com', 'X-Events-Key': 'public', 'Content-Type': 'application/json', 'User-Agent': MAC_CHROME } }));
  assert.equal(response.status, 200);
  assert.equal(writes[0][0].device_type, 'desktop');
  assert.equal(writes[0][0].browser, 'Chrome');
}

// These checks also run when this file is included by the whole browser contract.
const { default: test } = await import('node:test');
const { mergeDeviceProps } = await import('./events_device.ts');
const { execFileSync } = await import('node:child_process');
const facts = {
  os_version: '15.4', device_model: 'Pixel 9', cpu_architecture: 'arm', cpu_bitness: '64',
  gpu_renderer: 'Apple M4', connection_type: '4g', cpu_cores: 8, device_memory_gb: 8,
  pixel_ratio: 2, touch_points: 0, color_depth: 24, connection_downlink_mbps: 0,
};
test('collector preserves valid optional facts and drops invalid facts per field', () => {
  for (const [field, value] of Object.entries(facts)) {
    const event = { [field]: value, custom: 'kept' };
    mergeDeviceProps(event, {});
    assert.deepEqual(event, { [field]: value, custom: 'kept' });
    for (const invalid of [null, true, {}, [], 'x'.repeat(129), -1, Infinity, NaN, 100001]) {
      const event = { [field]: invalid, event_name: 'PageViewed' };
      mergeDeviceProps(event, {});
      assert.deepEqual(event, { event_name: 'PageViewed' }, `${field} ${invalid}`);
    }
  }
  for (const [field, value] of Object.entries({ cpu_cores: 1.5, device_memory_gb: 0, pixel_ratio: 17, touch_points: 257, color_depth: 65 })) {
    const event = { [field]: value };
    mergeDeviceProps(event, {});
    assert.deepEqual(event, {});
  }
});
test('collector overrides only the iOS OS version', () => {
  for (const [ua, expected] of [
    ['Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X)', '18.5'],
    ['Mozilla/5.0 (iPad; CPU OS 17_4_1 like Mac OS X)', '17.4.1'],
    [MAC_CHROME, 'supplied'], ['Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'supplied'],
  ]) {
    const event = { os_version: 'supplied' };
    mergeDeviceProps(event, deviceProps(new Headers({ 'User-Agent': ua })));
    assert.equal(event.os_version, expected);
  }
});
for (const mode of ['present', 'absent', 'rejected', 'throws', 'webgl-failure']) {
  test(`emitter optional APIs: ${mode}`, () => {
    // Isolate module lifetime and browser globals from the main transport tests.
    execFileSync(process.execPath, ['--experimental-strip-types', '--input-type=module', '-e', `
      import assert from 'node:assert/strict';
      const mode = ${JSON.stringify(mode)};
      let resolveHints; let hintCalls = 0; let gpuCalls = 0;
      const hints = new Promise(resolve => { resolveHints = resolve; });
      const nav = { userAgent: 'browser', language: 'en', hardwareConcurrency: 8, deviceMemory: 8,
        maxTouchPoints: 0, connection: { effectiveType: '4g', downlink: 0 },
        userAgentData: { getHighEntropyValues: () => {
          hintCalls++;
          if (mode === 'throws') throw Error('denied');
          return mode === 'rejected' ? Promise.reject(Error('denied')) : hints;
        } } };
      if (mode === 'absent') for (const key of ['hardwareConcurrency', 'deviceMemory', 'maxTouchPoints', 'connection', 'userAgentData']) delete nav[key];
      Object.defineProperty(globalThis, 'navigator', { value: nav, configurable: true });
      globalThis.window = { location: new URL('https://example.com/'), screen: mode === 'absent' ? { width: 1, height: 1 } : { width: 1, height: 1, colorDepth: 24 }, innerWidth: 1, innerHeight: 1,
        ...(mode === 'absent' ? {} : { devicePixelRatio: 2 }) };
      globalThis.document = { title: 'Page', referrer: '', addEventListener() {}, createElement() {
        gpuCalls++; if (mode === 'webgl-failure') throw Error('disabled');
        return { getContext: () => mode === 'absent' ? null : { getExtension: name => name === 'WEBGL_debug_renderer_info' ? { UNMASKED_RENDERER_WEBGL: 1 } : null, getParameter: () => 'Generic GPU' } };
      } };
      globalThis.setTimeout = () => 1;
      globalThis.clearTimeout = () => {};
      const batches = [];
      globalThis.fetch = async (_url, options) => { batches.push(JSON.parse(options.body)); return new Response('{}'); };
      const { configureEvents, emitEvent, flushEvents } = await import('./events.ts');
      configureEvents({ publishableKey: 'public' });
      const options = { name: 'PageViewed', kind: 'analytics', type: 'page_view' };
      const queued = emitEvent(options);
      assert.ok(!('os_version' in queued));
      // A pending hint cannot hold a flush or an emitted page view.
      await flushEvents(); assert.equal(batches.length, 1);
      const late = emitEvent(options);
      resolveHints({ platformVersion: '15.4', model: 'Phone', architecture: 'arm', bitness: '64' });
      await new Promise(setImmediate);
      await flushEvents();
      const actual = batches[1].events[0];
      if (['present', 'webgl-failure'].includes(mode)) {
        for (const [field, value] of Object.entries({ os_version: '15.4', device_model: 'Phone', cpu_architecture: 'arm', cpu_bitness: '64' })) assert.equal(actual[field], value);
        assert.equal(late.os_version, '15.4');
      } else assert.ok(!('os_version' in actual));
      const synchronous = { cpu_cores: 8, device_memory_gb: 8, pixel_ratio: 2, color_depth: 24, touch_points: 0, connection_type: '4g', connection_downlink_mbps: 0 };
      for (const [field, value] of Object.entries(synchronous)) {
        if (mode === 'absent') assert.ok(!(field in actual), field);
        else assert.equal(actual[field], value, field);
      }
      if (['absent', 'webgl-failure'].includes(mode)) assert.ok(!('gpu_renderer' in actual));
      else assert.equal(actual.gpu_renderer, 'Generic GPU');
      assert.equal(gpuCalls, 1);
      assert.equal(hintCalls, mode === 'absent' ? 0 : 1);
    `], { cwd: new URL('.', import.meta.url), stdio: 'pipe' });
  });
}
test('Python and TypeScript collectors agree on optional fact fixtures', () => {
  const fixtures = [facts, {}, ...Object.keys(facts).map(field => ({ [field]: true })),
    { pixel_ratio: 17, touch_points: 0, cpu_cores: 1.5, cpu_bitness: '64', gpu_renderer: '😀'.repeat(128) }];
  const expected = fixtures.map(fixture => {
    const result = { ...fixture };
    mergeDeviceProps(result, {});
    return result;
  });
  const output = execFileSync('python3', ['-c', `
import json, sys
from events_device import merge_device_props
fixtures = json.load(sys.stdin)
for event in fixtures:
    merge_device_props(event, {})
print(json.dumps(fixtures))
`], { cwd: new URL('.', import.meta.url), input: JSON.stringify(fixtures), encoding: 'utf8' });
  assert.deepEqual(JSON.parse(output), expected);
});

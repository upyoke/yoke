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

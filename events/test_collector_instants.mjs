import test from 'node:test';
import assert from 'node:assert/strict';
import { createCollector } from './api-route.ts';
import { formatInstant, instantFromDate } from './events_timestamps.mjs';

test('collector receipt and refusal clocks use exact fixed-six UTC instants', async () => {
  const originalNow = Date.now;
  try {
    for (const now of [-123456, 0, 123456]) {
      Date.now = () => now;
      const writes = [], refusals = [];
      const handler = createCollector({
        publishableKey: 'public', allowedOrigins: ['https://app.example.com'],
        rateLimit: async () => 0,
        writeEvents: async events => { writes.push(events); },
        recordRefusal: async refusal => { refusals.push(refusal); },
      });
      const event = {
        event_id: crypto.randomUUID(), event_name: 'PageViewed', event_kind: 'analytics',
        event_type: 'page_view', event_time: '1969-12-31T23:59:59.123456Z',
        session_id: 'session', source_type: 'frontend',
        received_at: '1999-01-01T00:00:00Z',
      };
      const request = key => new Request(`https://app.example.com/api/events/${now}`, {
        method: 'POST', headers: {
          Origin: 'https://app.example.com', 'X-Events-Key': key,
          'Content-Type': 'application/json',
        }, body: JSON.stringify({ events: [event] }),
      });
      assert.equal((await handler(request('public'))).status, 200);
      const accepted = writes[0][0];
      assert.equal(accepted.received_at, instantFromDate(new Date(now)));
      assert.equal(accepted.received_at, formatInstant(accepted.received_at));
      assert.equal(accepted.event_time, event.event_time);
      assert.equal((await handler(request('invalid'))).status, 401);
      assert.equal(refusals.length, 1);
      assert.equal(refusals[0].window_start,
        instantFromDate(new Date(Math.floor(now / 60000) * 60000)));
    }
  } finally {
    Date.now = originalNow;
  }
});

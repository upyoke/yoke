import rules from './attribution_rules.json' with { type: 'json' };
/** Frontend envelopes and retrying batches. One fetch per batch. */
import { MAX_ENVELOPE_BYTES, MAX_CONTEXT_FIELD_BYTES, MAX_BATCH_SIZE } from './events_types.ts';
import type { EventEnvelope, EmitOptions } from './events_types.ts';
import { getSystemProps, getSessionProps, getOrgProps, getPageProps, getDeviceProps } from './events_props.ts';
import { getAttributionProps, configureAttribution } from './events_capture.ts';

const queue: EventEnvelope[] = [];
const FLUSH_INTERVAL_MS = rules.limits.flush_interval_ms;
let timer: ReturnType<typeof setTimeout> | null = null;
let flight: Promise<void> | null = null;
let retryAt = 0;
let endpoint = '/api/events';
let key = '';

export function configureEvents(config: { publishableKey: string; endpoint?: string; attributionEndpoint?: string }): void {
  if (!config.publishableKey) throw new Error('publishable_key_required: configureEvents with the collector public key');
  key = config.publishableKey;
  endpoint = config.endpoint || '/api/events';
  configureAttribution(config.attributionEndpoint || '/api/events/attribution', key);
}

export function buildEvent(options: EmitOptions): EventEnvelope {
  const context = Object.fromEntries(Object.entries(options.context || {}).map(([k, v]) =>
    [k, typeof v === 'string' ? v.slice(0, MAX_CONTEXT_FIELD_BYTES) : v]));
  const event: EventEnvelope = {
    event_id: crypto.randomUUID(), event_name: options.name, event_kind: options.kind,
    event_type: options.eventType, event_time: new Date().toISOString(),
    event_outcome: options.outcome ?? null, severity: options.severity ?? 'INFO',
    source_type: 'frontend', duration_ms: options.durationMs ?? null,
    ...getSystemProps(), ...getSessionProps(), ...getOrgProps(options.orgId),
    ...getPageProps(), ...getDeviceProps(), ...getAttributionProps(), context,
  };
  if (new TextEncoder().encode(JSON.stringify(event)).length > MAX_ENVELOPE_BYTES) {
    event.context = { _truncated: true };
  }
  if (new TextEncoder().encode(JSON.stringify(event)).length > MAX_ENVELOPE_BYTES) {
    throw new Error('event_too_large: reduce page title, URL, or property sizes below 64 KB');
  }
  return event;
}

function schedule(delay = FLUSH_INTERVAL_MS): void {
  if (!timer && queue.length) {
    timer = setTimeout(() => { timer = null; void flushEvents(); }, delay);
  }
}

export function emitEvent(options: EmitOptions, props: Record<string, unknown> = {}): EventEnvelope {
  if (!key) throw new Error('publishable_key_required: call configureEvents before emitting');
  const event = { ...buildEvent(options), ...props };
  if (queue.length >= rules.limits.queue_events) {
    queue.shift();
    console.warn('[events] batch_queue_full: oldest event discarded; restore collector delivery');
  }
  queue.push(event);
  if (queue.length >= 10) void flushEvents();
  else schedule();
  return event;
}

function retryDelay(response: Response): number {
  const value = response.headers.get('Retry-After');
  const seconds = Number(value);
  if (value && Number.isFinite(seconds)) return Math.max(1000, seconds * 1000);
  const date = value ? Date.parse(value) : NaN;
  return Number.isFinite(date) ? Math.max(1000, date - Date.now()) : FLUSH_INTERVAL_MS;
}

export async function flushEvents(): Promise<void> {
  if (flight) return flight;
  if (timer) { clearTimeout(timer); timer = null; }
  if (!queue.length) return;
  if (Date.now() < retryAt) { schedule(retryAt - Date.now()); return; }
  // Keepalive has a browser-wide ~64 KB budget. Bound ordinary batches below it.
  let count = 0;
  let bytes = 16;
  while (count < queue.length && count < MAX_BATCH_SIZE) {
    const size = new TextEncoder().encode(JSON.stringify(queue[count])).length + 1;
    if (count && bytes + size > rules.limits.keepalive_bytes) break;
    bytes += size; count++;
  }
  const batch = queue.splice(0, count);
  function requeue(error: unknown): void {
    queue.unshift(...batch);
    if (queue.length > rules.limits.queue_events) {
      queue.length = rules.limits.queue_events;
      console.warn('[events] batch_queue_full: newest pending events discarded while preserving retry ids; restore delivery');
    }
    retryAt = Math.max(retryAt, Date.now() + FLUSH_INTERVAL_MS);
    console.warn('[events] batch_requeued: network, rate limit or server failure; retry after backoff', error);
  }
  flight = (async () => {
    try {
      let response: Response;
      try {
        response = await fetch(endpoint, {
          method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Events-Key': key },
          body: JSON.stringify({ events: batch }), keepalive: bytes <= rules.limits.keepalive_bytes, credentials: 'same-origin',
        });
      } catch (error) {
        requeue(error);
        return;
      }
      if (!response.ok) {
        if (response.status !== 429 && (response.status < 500 || response.status >= 600)) {
          const refusal = await response.json().catch(() => null);
          console.warn(`[events] batch_refused: ${refusal?.error || `collector_http_${response.status}`}; ${refusal?.recovery || 'correct collector configuration or payload before sending new events'}`);
          retryAt = 0;
          return;
        }
        retryAt = Date.now() + (response.status === 429 ? retryDelay(response) : FLUSH_INTERVAL_MS);
        requeue(`collector_http_${response.status}`);
        return;
      }
      retryAt = 0;
    } catch (error) {
      console.warn('[events] batch_delivery_invalid: batch discarded; repair transport or payload', error);
    } finally {
      flight = null;
      schedule(Math.max(FLUSH_INTERVAL_MS, retryAt - Date.now()));
    }
  })();
  return flight;
}

if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') void flushEvents();
  });
}

export { captureAttribution, getStoredAttribution, getAttributionProps } from './events_capture.ts';
export type { AttributionData, Touch } from './events_attribution.ts';
export type { EventEnvelope, EmitOptions } from './events_types.ts';

/** Framework-neutral factories: wire returned handlers into your project's routes. */
import { MAX_BATCH_SIZE, MAX_ENVELOPE_BYTES, MAX_REQUEST_BYTES } from './events_types.ts';
import { sanitizePath, sanitizeUrl, isBot } from './events_attribution.ts';
import { createAttributionCookie } from './events_cookie.ts';
import { createAttributionHandoff, handoffOrigin } from './events_handoff.ts';

export interface CollectorConfig {
  publishableKey: string;
  allowedOrigins: string[];
  // Durable/shared rate limiter. Return milliseconds to wait, or zero to admit.
  rateLimit: (request: Request) => Promise<number>;
  // Persist/dedupe by event_id; stamp authenticated identity and project on the server.
  writeEvents: (events: Record<string, unknown>[], request: Request) => Promise<void>;
  // Optional disposable diagnostics: called at most once per refusal kind per minute
  // in this process. Store keyed by refusal_id; nothing operational may read it.
  recordRefusal?: (refusal: CollectorRefusal) => Promise<void> | void;
}
export interface CollectorRefusal {
  refusal_id: string; reason: string; status: number; route: string;
  origin: string; host: string; window_start: string;
}
// Beyond this distance from receipt a client clock or long-queued retry is flagged.
export const CLIENT_TIME_TOLERANCE_SECONDS = 300;
const REFUSAL_WINDOW_MS = 60_000;
const recordedRefusals = new Set<string>();
async function noteRefusal(record: NonNullable<CollectorConfig['recordRefusal']>, request: Request, response: Response) {
  try {
    const window = Math.floor(Date.now() / REFUSAL_WINDOW_MS) * REFUSAL_WINDOW_MS;
    const { error } = await response.clone().json();
    const url = new URL(request.url);
    const refusalId = `${error}:${response.status}:${url.pathname}:${window}`;
    if (recordedRefusals.has(refusalId)) return;
    for (const key of recordedRefusals) if (Number(key.split(':').at(-1)) < window) recordedRefusals.delete(key);
    recordedRefusals.add(refusalId);
    await record({ refusal_id: refusalId, reason: String(error), status: response.status, route: url.pathname,
      origin: (request.headers.get('Origin') || '').slice(0, 200), host: url.host, window_start: new Date(window).toISOString() });
  } catch (error) {
    console.warn('[events] collector_refusal_record_failed: the refusal was returned but not recorded; restore recordRefusal storage', error);
  }
}
function recorded(config: CollectorConfig, handler: (request: Request) => Promise<Response>) {
  return async function recordedHandler(request: Request): Promise<Response> {
    const response = await handler(request);
    if (response.status >= 400 && config.recordRefusal) await noteRefusal(config.recordRefusal, request, response);
    return response;
  };
}
function reply(status: number, error: string, recovery: string, headers: Record<string, string> = {}) {
  return Response.json({ error, recovery }, { status, headers });
}
function validateConfig(config: CollectorConfig) {
  if (!config.publishableKey || !config.allowedOrigins.length || !config.rateLimit || !config.writeEvents) {
    throw new Error('collector_configuration_invalid: configure public key, exact origins, rate limiter and deduplicating event sink');
  }
}
async function admit(request: Request, config: CollectorConfig): Promise<Response | null> {
  if (!config.allowedOrigins.includes(request.headers.get('Origin') || '')) {
    return reply(403, 'origin_not_allowed', 'Use a configured exact origin; configure CORS separately for cross-origin collectors.');
  }
  if (request.headers.get('X-Events-Key') !== config.publishableKey) {
    return reply(401, 'publishable_key_invalid', 'Configure the collector publishable key in configureEvents.');
  }
  const delay = await config.rateLimit(request);
  if (delay > 0) return reply(429, 'rate_limited', 'Retry after Retry-After using the same event ids.', { 'Retry-After': String(Math.ceil(delay / 1000)) });
  return null;
}
async function readJson(request: Request) {
  if (!request.headers.get('Content-Type')?.toLowerCase().startsWith('application/json')) throw new Error('content_type_invalid');
  const reader = request.body?.getReader();
  if (!reader) throw new Error('json_invalid');
  const chunks: Uint8Array[] = [];
  let length = 0;
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    length += value.length;
    if (length > MAX_REQUEST_BYTES) { await reader.cancel(); throw new Error('payload_too_large'); }
    chunks.push(value);
  }
  const body = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.length; }
  try { return JSON.parse(new TextDecoder().decode(body)); }
  catch { throw new Error('json_invalid'); }
}

export function createCollector(config: CollectorConfig) {
  validateConfig(config);
  return recorded(config, async function POST(request: Request): Promise<Response> {
    const receivedAt = Date.now();
    try {
      if (request.method !== 'POST') return reply(405, 'method_not_allowed', 'Use POST.');
      const refusal = await admit(request, config);
      if (refusal) return refusal;
      const body = await readJson(request);
      if (!body || !Array.isArray(body.events) || !body.events.length || body.events.length > MAX_BATCH_SIZE) {
        return reply(400, 'events_invalid', 'Send 1..50 frontend analytics envelopes in events.');
      }
      for (const event of body.events) {
        if (!event || typeof event !== 'object' || Array.isArray(event) ||
          ['event_id', 'event_name', 'event_kind', 'event_type', 'event_time', 'session_id'].some(k => typeof event[k] !== 'string' || !event[k]) ||
          event.source_type !== 'frontend' || event.event_kind !== 'analytics' || !Number.isFinite(Date.parse(event.event_time))) {
          return reply(400, 'envelope_invalid', 'Use the frontend analytics emitter with a session id and ISO event_time.');
        }
        if (new TextEncoder().encode(JSON.stringify(event)).length > MAX_ENVELOPE_BYTES) {
          return reply(413, 'event_too_large', 'Reduce the envelope below 64 KB.');
        }
        event.page_url = sanitizeUrl(event.page_url || '');
        event.referrer = sanitizeUrl(event.referrer || '');
        if (typeof event.page_path === 'string') event.page_path = sanitizePath(event.page_path);
        event.is_bot = isBot(request.headers.get('User-Agent') || '');
        delete event.actor_id; delete event.org_id;
        // Order by receipt, never the browser clock; keep event_time as the client's claim.
        event.received_at = new Date(receivedAt).toISOString();
        event.client_time_offset_seconds = Math.round((Date.parse(event.event_time) - receivedAt) / 1000);
        event.client_time_skewed = Math.abs(event.client_time_offset_seconds) > CLIENT_TIME_TOLERANCE_SECONDS;
      }
      await config.writeEvents(body.events, request);
      return Response.json({ accepted: body.events.length });
    } catch (error) {
      const reason = error instanceof Error ? error.message : '';
      if (['json_invalid', 'content_type_invalid', 'payload_too_large'].includes(reason)) {
        return reply(reason === 'payload_too_large' ? 413 : 400, reason, 'Send application/json within the 512 KB request limit.');
      }
      console.warn('[events] collector_unavailable: inspect rate limiter or event sink', error);
      return reply(503, 'collector_unavailable', 'Retry the same event ids after restoring the limiter or sink.');
    }
  });
}

export async function createAttributionHandler(config: CollectorConfig & { signingSecret: string; siteDomain: string }) {
  validateConfig(config);
  const cookie = await createAttributionCookie(config.signingSecret, config.siteDomain);
  return recorded(config, async function handler(request: Request): Promise<Response> {
    try {
      const refusal = await admit(request, config);
      if (refusal) return refusal;
      if (request.method === 'GET') return Response.json(await cookie.readVerified(request.headers.get('Cookie') || ''), { headers: { 'Cache-Control': 'no-store' } });
      if (request.method !== 'POST') return reply(405, 'method_not_allowed', 'Use GET to read or POST to capture.');
      const body = await readJson(request);
      if (!body || typeof body.url !== 'string' || typeof body.referrer !== 'string') return reply(400, 'attribution_input_invalid', 'Send url and referrer strings.');
      const { record, setCookie } = await cookie.capture(request.headers.get('Cookie') || '', body.url, body.referrer);
      return Response.json(record, { headers: { 'Set-Cookie': setCookie, 'Cache-Control': 'no-store' } });
    } catch (error) {
      const reason = error instanceof Error ? error.message : 'attribution_unavailable';
      return reply(400, reason.split(':')[0], reason.includes(':') ? reason.split(':').slice(1).join(':').trim() : 'Check capture input, signing secret and rate limiter.');
    }
  });
}

export async function createAttributionHandoffHandler(config: CollectorConfig & {
  signingSecret: string; siteDomain: string;
  consumeNonce: (nonce: string, expires: number) => Promise<boolean>;
}) {
  validateConfig(config);
  if (!config.consumeNonce) throw new Error('attribution_handoff_storage_required: supply durable atomic nonce consumption');
  const handoff = await createAttributionHandoff(config.signingSecret, config.siteDomain);
  return recorded(config, async function handler(request: Request): Promise<Response> {
    try {
      const refusal = await admit(request, config);
      if (refusal) return refusal;
      if (request.method !== 'POST') return reply(405, 'method_not_allowed', 'Use POST for attribution hand-off.');
      handoffOrigin(new URL(request.url).origin);
      const body = await readJson(request);
      if (!body || typeof body !== 'object') throw new Error('attribution_input_invalid: send a JSON object');
      const headers = { 'Cache-Control': 'no-store' };
      if (new URL(request.url).pathname.endsWith('/redeem')) {
        const { record, setCookie } = await handoff.redeem(body.token, new URL(request.url).origin, config.consumeNonce);
        return Response.json(record, { headers: { ...headers, 'Set-Cookie': setCookie } });
      }
      return Response.json(await handoff.mint(request.headers.get('Cookie') || '', body.audience), { headers });
    } catch (error) {
      const message = error instanceof Error ? error.message : '';
      if (message.startsWith('attribution_') || ['json_invalid', 'content_type_invalid', 'payload_too_large'].includes(message)) {
        const [reason, ...recovery] = message.split(':');
        return reply(400, reason, recovery.join(':').trim() || 'Send application/json within the 512 KB request limit.', { 'Cache-Control': 'no-store' });
      }
      console.warn('[events] attribution_handoff_unavailable: restore durable nonce storage');
      return reply(503, 'attribution_handoff_unavailable', 'Restore durable nonce storage and restart sign-in.', { 'Cache-Control': 'no-store' });
    }
  });
}

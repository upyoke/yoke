# JS/TS Implementation Template (events.ts)

Cross-link back from [structured-logging-standard.md](../structured-logging-standard.md) for the canonical envelope, [property-groups.md](property-groups.md) for the field definitions, [source-type-composition.md](source-type-composition.md) for the `frontend` source-type composition, and [python-templates.md](python-templates.md) for the agent/system/backend emitters.

Reference implementation for `frontend` source type. Complete module with all property group builders, batching, and attribution support.

```typescript
/**
 * Structured event emitter -- JS/TS reference implementation.
 *
 * Usage:
 * import { emitEvent } from './events';
 *
 * emitEvent({
 * name: 'PageViewed',
 * kind: 'analytics',
 * eventType: 'page_view',
 * context: { tab: 'orders' },
 * });
 */

// --- Types ---

type EventKind = 'analytics' | 'system' | 'audit' | 'security' | 'metric';
type SourceType = 'agent' | 'backend' | 'frontend' | 'system';
type Severity = 'DEBUG' | 'INFO' | 'WARN' | 'ERROR' | 'FATAL';
type EventOutcome = 'completed' | 'failed' | 'skipped' | null;

interface EventEnvelope {
 event_id: string;
 event_name: string;
 event_kind: EventKind;
 event_type: string;
 event_time: string;
 event_outcome: EventOutcome;
 severity: Severity;
 source_type: SourceType;
 duration_ms: number | null;
 [key: string]: unknown;
 context: Record<string, unknown>;
}

interface EmitOptions {
 name: string;
 kind: EventKind;
 eventType: string;
 outcome?: EventOutcome;
 severity?: Severity;
 durationMs?: number;
 context?: Record<string, unknown>;
 orgId?: string;
}

// --- Property Group Builders ---

function getSystemProps(): Record<string, unknown> {
 return {
 environment: process.env.NEXT_PUBLIC_APP_ENV ?? 'development',
 service: 'web',
 service_version: process.env.NEXT_PUBLIC_APP_VERSION ?? null,
 project: process.env.NEXT_PUBLIC_PROJECT ?? 'yoke',
 };
}

function getSessionProps(): Record<string, unknown> {
 let sessionId = sessionStorage.getItem('event_session_id');
 if (!sessionId) {
 sessionId = crypto.randomUUID();
 sessionStorage.setItem('event_session_id', sessionId);
 }
 return {
 session_id: sessionId,
 session_start_time: sessionStorage.getItem('event_session_start') ?? null,
 };
}

function getOrgProps(
 orgId?: string,
): Record<string, unknown> {
 return {
 org_id: orgId ?? null,
 org_name: null,
 org_plan: null,
 };
}

function getPageProps(): Record<string, unknown> {
 return {
 page_url: window.location.href,
 page_path: window.location.pathname,
 page_title: document.title,
 referrer: document.referrer || null,
 };
}

function getDeviceProps(): Record<string, unknown> {
 const ua = navigator.userAgent;
 return {
 user_agent: ua,
 browser: parseBrowser(ua),
 os: parseOS(ua),
 device_type: detectDeviceType(),
 };
}

function getAttributionProps(): Record<string, unknown> {
 // See Section E for full attribution lifecycle
 const stored = getStoredAttribution();
 return {
 utm_source: stored.utm_source ?? null,
 utm_medium: stored.utm_medium ?? null,
 utm_campaign: stored.utm_campaign ?? null,
 utm_term: stored.utm_term ?? null,
 utm_content: stored.utm_content ?? null,
 referrer_domain: stored.referrer_domain ?? null,
 acquisition_channel: stored.acquisition_channel ?? null,
 };
}

// --- Event Builder ---

function buildEvent(options: EmitOptions): EventEnvelope {
 const envelope: EventEnvelope = {
 // event_props
 event_id: crypto.randomUUID(),
 event_name: options.name,
 event_kind: options.kind,
 event_type: options.eventType,
 event_time: new Date().toISOString(),
 event_outcome: options.outcome ?? null,
 severity: options.severity ?? 'INFO',
 source_type: 'frontend',
 duration_ms: options.durationMs ?? null,

 // system_props
 ...getSystemProps(),

 // session_props
 ...getSessionProps(),

 // org_props; authenticated receivers stamp actor_id server-side
 ...getOrgProps(options.orgId),

 // page_props
 ...getPageProps(),

 // device_props
 ...getDeviceProps(),

 // marketing_attribution_props (on all events for attribution analysis)
 ...getAttributionProps(),

 // context
 context: enforceContextLimits(options.context ?? {}),
 };

 return envelope;
}

// --- Emitter with Batching ---

const EVENT_QUEUE: EventEnvelope[] = [];
let flushTimer: ReturnType<typeof setTimeout> | null = null;
const BATCH_SIZE = 10;
const FLUSH_INTERVAL_MS = 5000;
const API_ENDPOINT = '/api/events';

function emitEvent(options: EmitOptions): EventEnvelope {
 const event = buildEvent(options);
 EVENT_QUEUE.push(event);

 if (EVENT_QUEUE.length >= BATCH_SIZE) {
 flushEvents();
 } else if (!flushTimer) {
 flushTimer = setTimeout(flushEvents, FLUSH_INTERVAL_MS);
 }

 return event;
}

async function flushEvents(): Promise<void> {
 if (flushTimer) {
 clearTimeout(flushTimer);
 flushTimer = null;
 }

 if (EVENT_QUEUE.length === 0) return;

 const batch = EVENT_QUEUE.splice(0, 50); // Max 50 per request

 try {
 const response = await fetch(API_ENDPOINT, {
 method: 'POST',
 headers: { 'Content-Type': 'application/json' },
 body: JSON.stringify({ events: batch }),
 keepalive: true, // Survives page navigation
 });

 if (!response.ok && response.status !== 429) {
 console.warn('[events] Flush failed:', response.status);
 }
 } catch {
 // Graceful degradation -- never crash on emit failure
 console.warn('[events] Flush failed: network error');
 }
}

// Flush on page unload
if (typeof window !== 'undefined') {
 window.addEventListener('visibilitychange', () => {
 if (document.visibilityState === 'hidden') {
 flushEvents();
 }
 });
}

// --- Helpers ---

function enforceContextLimits(
 ctx: Record<string, unknown>,
): Record<string, unknown> {
 const result: Record<string, unknown> = {};
 for (const [key, value] of Object.entries(ctx)) {
 if (typeof value === 'string' && value.length > 2048) {
 result[key] = value.slice(0, 2048);
 } else {
 result[key] = value;
 }
 }
 return result;
}

function parseBrowser(ua: string): string {
 if (ua.includes('Chrome')) return `Chrome ${ua.match(/Chrome\/([\d.]+)/)?.[1] ?? ''}`.trim();
 if (ua.includes('Firefox')) return `Firefox ${ua.match(/Firefox\/([\d.]+)/)?.[1] ?? ''}`.trim();
 if (ua.includes('Safari')) return `Safari ${ua.match(/Version\/([\d.]+)/)?.[1] ?? ''}`.trim();
 return 'Unknown';
}

function parseOS(ua: string): string {
 if (ua.includes('Mac OS X')) return `macOS ${ua.match(/Mac OS X ([\d_]+)/)?.[1]?.replace(/_/g, '.') ?? ''}`.trim();
 if (ua.includes('Windows')) return 'Windows';
 if (ua.includes('Linux')) return 'Linux';
 if (ua.includes('Android')) return 'Android';
 if (ua.includes('iPhone') || ua.includes('iPad')) return 'iOS';
 return 'Unknown';
}

function detectDeviceType(): string {
 if (typeof window === 'undefined') return 'unknown';
 const width = window.innerWidth;
 if (width < 768) return 'mobile';
 if (width < 1024) return 'tablet';
 return 'desktop';
}

// Stub -- full implementation in Section E
function getStoredAttribution(): Record<string, string | null> {
 return {};
}

export {
 emitEvent,
 buildEvent,
 flushEvents,
 getSystemProps,
 getSessionProps,
 getOrgProps,
 getPageProps,
 getDeviceProps,
 getAttributionProps,
 type EventEnvelope,
 type EmitOptions,
 type EventKind,
 type SourceType,
 type Severity,
};
```

---

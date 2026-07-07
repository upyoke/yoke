/**
 * Structured event emitter -- JS/TS reference implementation.
 *
 * Implements the canonical event envelope from the Structured Logging Standard
 * (Section D, Template 3). This module is a reference implementation intended
 * to be copied into each project that needs frontend event emission.
 *
 * Property group builders resolve fields from browser APIs and environment
 * variables (via NEXT_PUBLIC_ prefix for Next.js compatibility).
 *
 * The reference splits across four sibling files. Copy ALL FOUR into your
 * project together: events_types.ts, events_props.ts, events_attribution.ts,
 * and this file (events.ts). See templates/events/README.md for details.
 *
 * Usage:
 *   import { emitEvent, buildEvent, captureAttribution } from './events';
 *
 *   // Call once on app init to capture UTM params / referrer
 *   captureAttribution();
 *
 *   // Simple emit -- builds and queues in one call
 *   emitEvent({
 *     name: 'PageViewed',
 *     kind: 'analytics',
 *     eventType: 'page_view',
 *     context: { tab: 'orders' },
 *   });
 *
 *   // Composable style -- build prop groups, then assemble
 *   const event = buildEvent({
 *     name: 'ButtonClicked',
 *     kind: 'analytics',
 *     eventType: 'interaction',
 *     outcome: 'completed',
 *     context: { button_id: 'checkout', position: 'hero' },
 *     userId: 'usr_a1b2c3d4',
 *     orgId: 'org_x1y2z3',
 *   });
 */

import {
  MAX_ENVELOPE_BYTES,
  MAX_CONTEXT_FIELD_BYTES,
  type EventEnvelope,
  type EmitOptions,
  type EventKind,
  type SourceType,
  type Severity,
  type EventOutcome,
  type AttributionData,
} from './events_types';
import {
  getSystemProps,
  getSessionProps,
  getUserProps,
  getPageProps,
  getDeviceProps,
} from './events_props';
import {
  captureAttribution,
  getStoredAttribution,
  extractReferrerDomain,
  inferChannel,
  getAttributionProps,
} from './events_attribution';

// ---------------------------------------------------------------------------
// Event Builder
// ---------------------------------------------------------------------------

/**
 * Build a complete event envelope.
 *
 * Merges all frontend property groups (system, session, user, org, page,
 * device, attribution) into a flat envelope matching the canonical schema.
 *
 * Args:
 *   options.name: PascalCase event name (e.g., "PageViewed")
 *   options.kind: Event kind enum (analytics, system, audit, security, metric)
 *   options.eventType: Domain-specific type string (e.g., "page_view")
 *   options.outcome: Event outcome (completed, failed, skipped, or null)
 *   options.severity: Log severity (DEBUG, INFO, WARN, ERROR, FATAL)
 *   options.durationMs: Operation duration in milliseconds
 *   options.context: Event-specific payload dict
 *   options.userId: User identifier for user_props
 *   options.orgId: Organization identifier for org_props
 *
 * Returns:
 *   Complete event envelope matching the canonical schema.
 */
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

    // user_props + org_props
    ...getUserProps(options.userId, options.orgId),

    // page_props
    ...getPageProps(),

    // device_props
    ...getDeviceProps(),

    // marketing_attribution_props (on all events for attribution analysis)
    ...getAttributionProps(),

    // context
    context: enforceContextLimits(options.context ?? {}),
  };

  // Enforce total envelope size (64 KB)
  const encoded = JSON.stringify(envelope);
  if (encoded.length > MAX_ENVELOPE_BYTES) {
    envelope.context = { _truncated: true };
  }

  return envelope;
}

// ---------------------------------------------------------------------------
// Emitter with Batching
// ---------------------------------------------------------------------------

const EVENT_QUEUE: EventEnvelope[] = [];
let flushTimer: ReturnType<typeof setTimeout> | null = null;
const BATCH_SIZE = 10;
const FLUSH_INTERVAL_MS = 5000;
const API_ENDPOINT = '/api/events';

/**
 * Build and emit an event.
 *
 * Events are queued and flushed in batches (up to 10 events or every 5
 * seconds) to minimize network requests. The queue is also flushed when
 * the page becomes hidden (tab switch, navigation).
 *
 * Returns the built event envelope for inspection or logging.
 */
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

/**
 * Flush the event queue to the /api/events endpoint.
 *
 * Sends up to 50 events per request. Uses keepalive to survive page
 * navigation. Never throws -- emit failures are silently swallowed
 * (graceful degradation principle from the standard).
 */
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Enforce context field size limits.
 * String fields exceeding 2KB are truncated.
 */
function enforceContextLimits(
  ctx: Record<string, unknown>
): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(ctx)) {
    if (typeof value === 'string' && value.length > MAX_CONTEXT_FIELD_BYTES) {
      result[key] = value.slice(0, MAX_CONTEXT_FIELD_BYTES);
    } else {
      result[key] = value;
    }
  }
  return result;
}

// ---------------------------------------------------------------------------
// Complete Example: PageViewed analytics event with all frontend prop groups
// ---------------------------------------------------------------------------
//
// To run this example, call emitPageViewedExample() after captureAttribution():
//
//   captureAttribution();
//   const event = emitPageViewedExample();
//   console.log(JSON.stringify(event, null, 2));
//
function emitPageViewedExample(): EventEnvelope {
  return emitEvent({
    name: 'PageViewed',
    kind: 'analytics',
    eventType: 'page_view',
    outcome: 'completed',
    userId: 'usr_a1b2c3d4',
    orgId: 'org_x1y2z3',
    context: {
      tab: 'orders',
      items_visible: 25,
    },
  });
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export {
  // Event building and emission
  emitEvent,
  buildEvent,
  flushEvents,

  // Property group builders (re-exported from events_props.ts)
  getSystemProps,
  getSessionProps,
  getUserProps,
  getPageProps,
  getDeviceProps,
  getAttributionProps,

  // Attribution lifecycle (re-exported from events_attribution.ts)
  captureAttribution,
  getStoredAttribution,
  extractReferrerDomain,
  inferChannel,

  // Example
  emitPageViewedExample,

  // Types (re-exported from events_types.ts)
  type EventEnvelope,
  type EmitOptions,
  type EventKind,
  type SourceType,
  type Severity,
  type EventOutcome,
  type AttributionData,
};

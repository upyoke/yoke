/**
 * Next.js API Route: /api/events
 *
 * Receives batched frontend events from the events.ts emitter, validates the
 * envelope structure, and writes to the events table (or proxies to a backend
 * API endpoint).
 *
 * This is an adaptable Pack implementation. Install it in a Next.js project at:
 *   app/api/events/route.ts    (App Router)
 *   pages/api/events.ts        (Pages Router -- adapt handler signature)
 *
 * The route accepts POST requests with a JSON body:
 *   { "events": [ ...EventEnvelope[] ] }
 *
 * Validation:
 * - Request body must contain an "events" array
 * - Array must contain 1..50 events
 * - Each event must have event_id, event_name, event_kind, event_type, event_time
 * - Total request body must not exceed 512 KB
 *
 * On success, returns { "accepted": N } with HTTP 200.
 * On validation failure, returns { "error": "..." } with HTTP 400.
 */

import { NextRequest, NextResponse } from 'next/server';

// ---------------------------------------------------------------------------
// Size limits
// ---------------------------------------------------------------------------
const MAX_BATCH_SIZE = 50;
const MAX_REQUEST_BYTES = 524288; // 512 KB

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

const REQUIRED_FIELDS = [
  'event_id',
  'event_name',
  'event_kind',
  'event_type',
  'event_time',
] as const;

const VALID_KINDS = new Set([
  'analytics',
  'system',
  'audit',
  'security',
  'metric',
]);

/**
 * Validate a single event envelope.
 * Returns null if valid, or an error string describing the issue.
 */
function validateEvent(
  event: Record<string, unknown>,
  index: number
): string | null {
  for (const field of REQUIRED_FIELDS) {
    if (!event[field]) {
      return `events[${index}]: missing required field "${field}"`;
    }
  }

  const kind = event.event_kind as string;
  if (!VALID_KINDS.has(kind)) {
    return `events[${index}]: invalid event_kind "${kind}"`;
  }

  return null;
}

// ---------------------------------------------------------------------------
// Route Handler (Next.js App Router)
// ---------------------------------------------------------------------------

export async function POST(request: NextRequest): Promise<NextResponse> {
  // Check Content-Type
  const contentType = request.headers.get('content-type');
  if (!contentType?.includes('application/json')) {
    return NextResponse.json(
      { error: 'Content-Type must be application/json' },
      { status: 400 }
    );
  }

  // Check request size
  const contentLength = request.headers.get('content-length');
  if (contentLength && parseInt(contentLength, 10) > MAX_REQUEST_BYTES) {
    return NextResponse.json(
      { error: 'Request body exceeds 512 KB limit' },
      { status: 413 }
    );
  }

  // Parse body
  let body: Record<string, unknown>;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { error: 'Invalid JSON body' },
      { status: 400 }
    );
  }

  // Validate events array
  const events = body.events;
  if (!Array.isArray(events)) {
    return NextResponse.json(
      { error: 'Request body must contain an "events" array' },
      { status: 400 }
    );
  }

  if (events.length === 0) {
    return NextResponse.json(
      { error: 'Events array must not be empty' },
      { status: 400 }
    );
  }

  if (events.length > MAX_BATCH_SIZE) {
    return NextResponse.json(
      { error: `Events array exceeds max batch size of ${MAX_BATCH_SIZE}` },
      { status: 400 }
    );
  }

  // Validate each event
  for (let i = 0; i < events.length; i++) {
    const err = validateEvent(events[i], i);
    if (err) {
      return NextResponse.json({ error: err }, { status: 400 });
    }
  }

  // -------------------------------------------------------------------------
  // Write events to storage
  //
  // Replace this section with your actual storage backend. Options:
  //
  // Option A: Write directly to a database (events table)
  //   await db.insert('events').values(events.map(e => ({
  //     event_id: e.event_id,
  //     event_name: e.event_name,
  //     event_kind: e.event_kind,
  //     event_type: e.event_type,
  //     event_time: e.event_time,
  //     payload: JSON.stringify(e),
  //   })));
  //
  // Option B: Proxy to a backend API endpoint
  //   await fetch(process.env.EVENTS_API_URL!, {
  //     method: 'POST',
  //     headers: { 'Content-Type': 'application/json' },
  //     body: JSON.stringify({ events }),
  //   });
  //
  // Option C: Write to a log file (JSONL format)
  //   for (const event of events) {
  //     fs.appendFileSync(logPath, JSON.stringify(event) + '\n');
  //   }
  // -------------------------------------------------------------------------

  // Default implementation: log to stdout (structured JSON lines)
  for (const event of events) {
    console.log(JSON.stringify(event));
  }

  return NextResponse.json({ accepted: events.length });
}

/**
 * Reject non-POST methods.
 */
export async function GET(): Promise<NextResponse> {
  return NextResponse.json(
    { error: 'Method not allowed. Use POST.' },
    { status: 405 }
  );
}

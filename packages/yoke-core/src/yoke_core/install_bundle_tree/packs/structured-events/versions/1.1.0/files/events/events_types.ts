/**
 * Shared event types. See events/README.md.
 */

// ---------------------------------------------------------------------------
// Size limits (from standard spec)
// ---------------------------------------------------------------------------
export const MAX_ENVELOPE_BYTES = 65536; // 64 KB total envelope
export const MAX_CONTEXT_FIELD_BYTES = 2048; // 2 KB per context string field

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type EventKind = 'analytics' | 'system' | 'audit' | 'security' | 'metric';
export type SourceType = 'agent' | 'backend' | 'frontend' | 'system';
export type Severity = 'DEBUG' | 'INFO' | 'WARN' | 'ERROR' | 'FATAL';
export type EventOutcome = 'completed' | 'failed' | 'skipped' | null;

export interface EventEnvelope {
  event_id: string;
  event_name: string;
  event_kind: EventKind;
  event_type: string;
  event_time: string;
  event_outcome: EventOutcome;
  severity: Severity;
  source_type: SourceType;
  duration_ms: number | null;
  context: Record<string, unknown>;
  [key: string]: unknown;
}

export interface EmitOptions {
  name: string;
  kind: EventKind;
  eventType: string;
  outcome?: EventOutcome;
  severity?: Severity;
  durationMs?: number;
  context?: Record<string, unknown>;
  orgId?: string;
}

export interface AttributionData {
  utm_source: string | null;
  utm_medium: string | null;
  utm_campaign: string | null;
  utm_term: string | null;
  utm_content: string | null;
  referrer_domain: string | null;
  acquisition_channel: string | null;
  captured_at: string | null;
}

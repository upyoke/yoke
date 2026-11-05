import rules from './attribution_rules.json' with { type: 'json' };
/** Shared envelope and collector limits. */
export const MAX_ENVELOPE_BYTES = rules.limits.envelope_bytes;
export const MAX_CONTEXT_FIELD_BYTES = rules.limits.context_field_bytes;
export const MAX_BATCH_SIZE = rules.limits.batch_size;
export const MAX_REQUEST_BYTES = rules.limits.request_bytes;
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

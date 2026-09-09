// Semantic color hints for state values. Workflow vocabularies remain
// definition-owned; unknown values intentionally render neutral.
//
// The families are the palette's own semantic pairs: `good` for healthy,
// `run` for in flight, `warn` for attention, `park` for a declared wait,
// `crit` for failure, `idle` for genuinely neutral. A meaningful state left
// out of this map falls through to grey, which reads as "nothing to see" —
// so a state worth showing belongs here even when its family is `idle`.

const FAMILIES = {
  implementing: "run",
  "reviewing-implementation": "run",
  "reviewed-implementation": "run",
  "polishing-implementation": "run",
  release: "run",
  new: "run",
  executing: "run",
  implemented: "good",
  done: "good",
  active: "good",
  idle: "idle",
  ended: "idle",
  // A session that parked itself is neither running nor neutral: it declared
  // a wait and takes it back on its next tool call. Grey read as "nothing
  // here", which is the opposite of what a park means.
  parked: "park",
  // A registered machine with no live relay is a reading, not an absence:
  // nothing can be launched there until it comes back.
  offline: "warn",
  connected: "good",
  succeeded: "good",
  blocked: "crit",
  failed: "crit",
  error: "crit",
  critical: "crit",
  unclear: "warn",
  warn: "warn",
  warning: "warn",
  stale: "warn",
  "possibly stale": "warn",
  "process-gone": "crit",
  silent: "warn",
  pass: "good",
  fail: "crit",
  skip: "idle",
  activation: "crit",
  integration: "warn",
  closure: "idle",
  provider_access: "run",
  test_resource: "good",
  declared_model: "idle",
  in_use: "run",
  "in use": "run",
  verified: "good",
  configured_unverified: "warn",
  "configured (unverified)": "warn",
  "not configured": "warn",
  configured: "warn",
  "project scoped": "idle",
  mixed: "warn",
  declared: "idle",
  pending: "warn",
  unavailable: "warn",
  enabled: "good",
  disabled: "idle",
  suspended: "crit",
  deleted: "crit",
  satisfied: "good",
  "not satisfied": "warn",
  "not satisfied yet": "warn",
  missing: "crit",
  // Genuinely nothing known, which is neutral. Amber implied the state was
  // itself something to act on.
  unknown: "idle",
  available: "good",
  ready: "good",
  passed: "good",
  waived: "good",
  queued: "idle",
  assigned: "run",
  launching: "run",
  awaiting_registration: "warn",
  injected: "run",
  acknowledged: "good",
  expired: "crit",
  cancelled: "idle",
  outcome_unknown: "warn",
  // Waiting on a person or an answer is attention, not neutral.
  waiting: "warn",
  probed: "run",
  running: "run",
  claimed: "run",
  "item-owned": "run",
  archived: "idle",
  planned: "idle",
  drafted: "idle",
  "needs review": "warn",
  // A run halted on a person is not idle and not failing; the generic
  // vocabulary had no word for it, so a gated card wore a grey pill.
  "awaiting approval": "warn",
  "awaiting review": "warn",
  "blocked on precondition": "crit",
  installed: "good",
  success: "good",
  waits: "idle",
  "next up": "run",
  activated: "good",
  stored: "good",
};

export function pillFamilyForState(value) {
  return FAMILIES[String(value || "").toLowerCase()] || "idle";
}

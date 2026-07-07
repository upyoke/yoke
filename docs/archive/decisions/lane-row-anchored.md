# Execution lane is row-anchored, not envelope-anchored

## Context

The session-offer routing layer used to read `execution_lane` from the
caller-supplied envelope (request body, `--lane` flag, or harness-emitted
session-offer envelope). The authoritative `execution_lane` column on
the `harness_sessions` row was set at session start and then largely
ignored by routing. Two failures cascaded:

1. A caller passing `--lane primary` could silently override the
   server-side lane policy even when the session belonged to a different
   lane.
2. Unknown / unconfigured lanes silently fail-open: routing accepted
   work for lanes that had no matching policy, and the resulting work
   could not be dispatched.

## Decision

Routing reads `execution_lane` from the `harness_sessions` row, not from
the offer envelope. Caller-supplied `--lane` and request-body
`execution_lane` are **advisory only** — mismatches emit
`SessionOfferLaneOverrideIgnored` and the row value wins.

Unknown / unconfigured lanes are no longer a fail-open: the offer emits
`WAIT` with `wait_reason='lane_policy_unknown'` and refuses to attribute
work to a lane that has no live policy.

## Consequences

- `service_client session-offer --lane X` is documented as advisory.
- Doctor's `HC-session-lane-mismatch` flags any session whose row lane
  conflicts with its offer envelope, surfacing legacy fixtures and
  any drift introduced by future writers.
- The session-decision lane gate is the single chokepoint; ad-hoc lane
  checks downstream were removed.

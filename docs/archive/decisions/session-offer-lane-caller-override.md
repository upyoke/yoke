# Session-offer lane settings are the default; a supplied lane overrides them

## Context

`harness_sessions.execution_lane` is written at session start from the
executor default-lane lookup. Callers may still pass `--lane` or a
request-body `execution_lane`. Treating that flag as advisory discarded
an explicit capability choice: lane membership is real
(`lane_paths.ALTMAN` covers refine, polish, usher, dash).

## Decision

The session-row lane is the default. When a caller supplies a lane
(other than the documented `default` sentinel), session-offer uses the
caller value for schedule filtering, envelope authorship, and
`decide_next_action`. The offer emits
`SessionOfferLaneOverrideApplied` with `caller_supplied`, `row_lane`,
and `resolved_lane`.

Unknown / unconfigured lanes still return `WAIT` with
`wait_reason='lane_policy_unknown'`.

## Consequences

- `/yoke do` does not pass `--lane`; the session-row default stands.
- The `--lane` flag remains on `yoke sessions offer` for callers that
  need an override.
- Historical `events` rows under the previous override name stay in
  the ledger; the registry row is retired so they do not register as
  rogue.

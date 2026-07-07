# Session identity spans episodes

## Context

A single Yoke `harness_sessions.session_id` may legitimately span multiple
episodes. Claude Desktop fires `HarnessSessionEnded` on transient signals
(laptop sleep, app reload, brief disconnect, idle timeout) and then resumes
the SAME conversation with the SAME `session_id`. The destructive guard at
`runtime.api.domain.sessions_lifecycle_destructive_guard.evaluate_destructive_end`
already defers a fresh end when heartbeats are inside the recovery window,
but the destructive close path eventually fires when both checks fail and
the operator returns later — at which point reactivation runs in
`sessions_lifecycle_registry.register_session`.

Before this decision the event ledger left the episode boundary implicit.
Querying "what did session X do" returned a mishmash of activity from the
prior episode plus the resumed episode, and lock inheritance from the prior
episode went unmarked. Operators had no single-predicate way to scope an
audit query to "this episode only."

Today's Codex sessions do not exhibit the same transient-signal class —
they have no equivalent of Claude Desktop's `SessionEnd` on sleep / reload
/ idle. But the identity-stable property would matter symmetrically if a
future Codex behavior introduced the same shape, so this decision is
recorded cross-harness even though the immediate emit surface is Claude's
reactivation path.

## Decision

`session_id` is permitted to span multiple episodes. Yoke does NOT mint
a new `session_id` on resume.

Each resumption is marked on the events ledger with a dedicated
`HarnessSessionResumed` event so audit queries can scope to "this episode
only" with a single `event_name` predicate. The marker is emitted from
`runtime.api.domain.sessions_lifecycle_resumption_emit.emit_session_resumed`,
called by `sessions_lifecycle_reactivation.emit_reactivated_with_released_claims`
after the existing `SessionReactivatedWithReleasedClaims` advisory and the
existing `SessionReactivationReacquiredClaims` auto-reacquire event.

Envelope contents:

- `session_id`
- `resumption: true`
- `prior_release_reason`: `"session_ended"` (the trigger that defines the
  episode boundary)
- `released_claim_count`, `reacquired_count`, `conflict_count`
- `claim_details`: per-target rows tagged
  `episode_scope=inherited|reacquired|conflict`, plus
  `new_claim_id` on reacquired entries.

Locks attached to the prior episode remain valid in the resumed episode.
The auto-reacquire path re-inserts the work claim row when there is no
conflicting live holder; when another live session legitimately holds the
target, recovery is explicit via
`python3 -m runtime.api.service_client claim-work --item YOK-N`. Either
way the same `session_id` retains authority over its claims across the
episode boundary — there is no per-episode handoff to coordinate.

Episode-scoped audit goes through `--current-episode`:

- `python3 -m runtime.api.cli.db_router events list --session-id <id> --current-episode`
  scopes the result to events whose `created_at` is at or after the most
  recent boundary event (`HarnessSessionResumed` if present, else
  `HarnessSessionStarted`) for that session. The flag requires an explicit
  `--session-id` and fails closed with a usage error otherwise. When the
  session has no boundary event recorded, the result is the empty set,
  not implicitly "all events for the session." The composition with other
  flags is AND.
- `python3 -m runtime.harness.harness_sessions who-claims <item-id> --current-episode`
  appends `episode_scope=current_episode|inherited_from_prior_episode|unknown`
  to the claim row and an `episode_boundary=<ts|none>` line so inherited
  claims remain visible. Audit MUST show inheritance; it never hides a
  claim merely because it predates the boundary.

The shared resolver
`runtime.api.domain.events_current_episode.resolve_current_episode_boundary`
is the single source of truth used by both surfaces. Adding new audit
surfaces should consume the same helper rather than re-implementing the
boundary query.

## Consequences

- Audit queries scoped to "this episode" cost one extra row lookup per
  call (most recent boundary event for the session, via the existing
  `idx_events_session_id` / `idx_events_created_at` indexes). No new
  composite index, schema column, or migration is required.
- A new `HarnessSessionResumed` event name appears on the registry —
  consumers that filter by `event_name` for boundary events should
  include both `HarnessSessionResumed` and `HarnessSessionStarted`.
- The `SessionReactivatedWithReleasedClaims` and
  `SessionReactivationReacquiredClaims` events are unchanged. The
  resumption marker is additive — it lands AFTER the existing pair on
  the reactivation path, so the reactivation auto-reacquire log is
  preserved verbatim.
- The full Claude-side policy text lives at
  `runtime/harness/claude/rules/session.md` (section
  `## Session Identity Spans Episodes (Claude-only)`). This decision
  record is the cross-harness pointer; future Codex symmetry work can
  amend the rules file or add a Codex-side rules file without changing
  this record.

# session-end (no flags) auto-releases active work-claims

Decision recorded 2026-05-24. Implemented under YOK-1855.

## Decision

Calling `python3 -m runtime.api.service_client session-end` (or the
wrapped `yoke session end` once YOK-1847's wrapper exposes the
command) with no flags auto-releases the session's active work-claims
with `release_reason='session_ended'` before marking the session
ended. The success JSON carries a top-level `released_claims` list
naming each released claim by `claim_id`, `target_kind`, and the
target-kind identifiers (`item_id`, `epic_id`+`task_num`, or
`process_key`+`conflict_group`).

This is Option B from the YOK-1855 vetting session. Option A (preserve
the `ACTIVE_CLAIM` rejection and document the manual `claim-release`
prerequisite in `/yoke do` Step D) was considered and rejected.

## Why

The previous contract refused with `ACTIVE_CLAIM`:

```json
{
  "success": false,
  "code": "ACTIVE_CLAIM",
  "message": "Session ... still holds 1 active claim(s): claim 2930 (item=1841). Claim release is agent-owned — use the operator override CLI or wait for stale-session reclamation."
}
```

Three reasons drove the flip:

1. **The hook path already auto-released.** When Claude Desktop fires
   `SessionEnd` on a session that is truly ending, the destructive
   branch in `runtime.api.domain.sessions_render_end.end_session`
   already auto-released claims through
   `sessions_lifecycle_destructive_guard.handle_release_claims_branch`.
   The explicit CLI `session-end` invocation refusing to do the same
   thing was a doctrinal split with no principled basis — both
   signals mean "this session is ending."

2. **Autonomous-execution Yoke is the operating mode.** Per
   CLAUDE.md's Yoke Authority rule, "Yoke is designed for the
   operator to kick off work and walk away." A cleanup step the loop
   could not autonomously execute was a regression of that principle,
   not a feature. Recipe-event evidence showed every `/yoke do`
   cleanup cycle hitting this on the first try and requiring manual
   `release-work-claim` before retrying `session-end`.

3. **Founder-build "safer" did not apply here.** The release is
   reversible at the data level — the claim row stays, just gets
   `released_at` stamped. The transient-signal protection that
   motivates the destructive-guard (Claude Desktop firing `SessionEnd`
   on laptop sleep / app reload / brief disconnect / idle timeout)
   lives in the `SessionEnd` *hook* path, not the explicit CLI path,
   and that protection stays intact under Option B because the
   no-flags CLI / `/yoke do` loop is asking to end deliberately.

## Evidence

- Recipe-event `2330fc43` (2026-05-24T16:11:38Z) cited the verbatim
  `ACTIVE_CLAIM` payload above.
- Recipe-event `12073532` (2026-05-24T16:16:36Z) cited the doc/code
  mismatch in `loop-followups.md` Step D: "Step D contract says: 'When
  the loop terminates, call `session-end` (no flags) to release claims
  and mark the session as ended.' It does NOT say: 'first release the
  work claim acquired by the routed handler when the handler failed
  before lifecycle finalize.'"
- The recipe-event log carried 5+ occurrences in the 7 days preceding
  the decision.

## Preserved invariants

- **CHAIN_PENDING still blocks.** Loop exits with budget remaining
  continue to fail closed unless the operator supplies
  `--override-chain-end --chain-end-rationale "<why>"`. YOK-1855 does
  not loosen this guard.
- **Transient-signal defer stays on the destructive branch.** The
  `--release-claims` hook path keeps the heartbeat-fresh and
  chain-pending defer protection (`TRANSIENT_END_DEFERRED` raised when
  the guard refuses). The no-flags CLI / loop path is deliberate; that
  protection is not appropriate there.
- **Operator override CLI unchanged.** `release-work-claim` (the
  operator-mediated single-claim release) keeps its semantics. The
  decision narrows the gap between automatic and operator-driven
  paths, not their roles.

## Implementation surface

- `runtime/api/domain/sessions_render_end_claim_release.py` (new
  helper) — enumerates active work-claims for a session, releases
  each through `release_work_claim_for_execution` so item, epic_task,
  and process targets all use the same typed release path and
  process-owned linked path claims cascade through the existing
  release behavior. Emits `HarnessSessionEndReleasedClaims` with
  `context.via="no_flags"` aggregating the cleanup outcome.
- `runtime/api/domain/sessions_render_end.py` —
  `end_session(release_claims=False)` now calls the helper instead
  of raising `ACTIVE_CLAIM`. CHAIN_PENDING ordering unchanged.
- `runtime/api/service_client_sessions_lifecycle_end.py` — success
  JSON gains the top-level `released_claims` field. Error JSON for
  `CHAIN_PENDING` / `TRANSIENT_END_DEFERRED` unchanged.
- `.agents/skills/yoke/do/loop-followups.md` Step D — updated to
  document the auto-release semantics and the `released_claims`
  payload.

## Trade-offs

- **`HarnessSessionEndRejectedActiveClaim` event no longer fires
  from production code.** The constant and registry entry remain
  defined; the rejection event was the audit signal for the previous
  contract, and historical occurrences in the event log retain
  meaning. Future paths could repurpose the constant if a new
  rejection class emerges, but it is not currently emitted.
- **Released claims through the no-flags path do not carry
  per-target `release_reason` arguments.** Every claim is released
  with `release_reason='session_ended'`. This matches the
  destructive-guard `release_claims=True` branch and the canonical
  enum in `sessions_lifecycle_release._RELEASE_REASON_SCHEMA_MAP`.

## Regression guard

AC-8 of YOK-1855: the 7-day post-merge `OuroborosRecipeEventAppended`
window shows zero new entries matching the `ACTIVE_CLAIM` on
`session-end` pattern. The recipe-event channel is the structural
regression signal; no new Doctor HC is required.

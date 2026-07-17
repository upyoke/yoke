# Advance — Path Claim Activation

> **Orchestrator role:** For implementation-entry advances, this phase
> runs inside `worktree_preflight.run_preflight` via
> `activate_path_claims` (the step helper in
> `worktree_preflight_steps`). The advance implementation-entry
> orchestrator does not call `advance_path_claim_activation.run_activation_phase`
> separately — that's the "exactly one claim/activation/worktree
> boundary" rule. The standalone CLI / `run_activation_phase` entrypoint
> below remains for operators reconciling activation outside the full
> worktree-preflight bundle.

Called by the advance router after preflight gates pass and before the
worktree phase. Closes the seam between the path-claim-required gate
(declared at idea/refine time) and the worktree door-lock check (which
refuses anything not in `state='active'`). Operators previously had to
discover by runtime error that activation was a separate manual step;
this phase performs it automatically.

**Context variables** (set by router): `{N}`, `_type`, `_status`,
`_target`, `_item_project`, `--force` flag

**Enforcement owner:** `yoke_core.domain.advance_path_claim_activation`

---

## Applicability

Run when:
- target is `implementing` (the implementation entry transition), and
- the item type is not `epic`, and
- the actor has at least one non-terminal `path_claims` row for the item.

Skip when:
- `--no-worktree` is passed (no worktree door-lock will fire),
- target is not `implementing`, or
- the item has no path claims (the path-claim-required gate has already
  enforced declaration where it applies; not every project / item type
  carries a claim).

## Invocation

Normal implementation-entry advance does not have an agent-facing activation
command: `worktree_preflight.run_preflight` invokes this phase in-process. The
standalone activation entrypoint is a Yoke source-dev/admin boundary in
`yoke_core.domain.advance_path_claim_activation` for operators reconciling
activation outside the full worktree-preflight bundle; it is not a registered
product CLI wrapper and should not be taught as normal advance flow.

Exit codes:

| Exit | Meaning                                                                  |
|---   |---                                                                       |
| 0    | All planned claims activated; stdout: ``activated=[ids]``.               |
| 1    | One or more claims are blocked or refs have diverged; stderr lists ``BLOCKED:`` and ``DIVERGED:`` rows. Stop the advance. |
| 2    | Missing item, missing owner/source actor, or invalid ``--item`` value. Stop the advance and surface the stderr message. |

The CLI is the guard-compatible replacement for the legacy inline
heredoc. Skill prose, persona docs, and harness adapters route through
this entrypoint exclusively — no inlined ``python3 - <<PY`` blocks. The
domain function :func:`run_activation_phase` remains the in-process
caller surface for tests and adjacent Yoke surfaces.

## Outcomes

The phase walks every non-terminal `path_claims` row for the
`(item_id, actor_id)` pair and dispatches per state:

| Claim state at entry | Action                                                      | Result attribute        |
|---                   |---                                                          |---                      |
| `planned`            | Resolve integration head, ensure snapshot, activate         | `outcomes[i].state_after = "active"` |
| `blocked`            | Surface `"claim N is blocked: <reason>"` and stop the phase | `blocked_errors`        |
| `active`             | No-op (idempotent re-entry)                                 | `outcomes[i]` recorded  |

When `origin/<integration_target>` and `refs/heads/<integration_target>`
have *diverged* (neither is an ancestor of the other), the resolver
raises `IntegrationTargetDiverged` and the phase records the message in
`result.diverged_error`. Operators must reconcile (push, pull, or
rebase) before retrying.

## What activation does

1. Reads each claim's `integration_target` (typically `main`).
2. Calls
   `yoke_core.domain.path_claims_integration_resolver.resolve_integration_head_with_divergence_check`
   with the target project's local checkout path. The resolver:
   - resolves origin-then-local with explicit divergence check, and
   - calls
     `yoke_core.domain.path_snapshots.ensure_snapshot_at` so the
     snapshot row is built inline if missing — no cold-start
     "no path snapshot at SHA" surprise.
3. Calls
   `yoke_core.domain.path_claims_register.activate_with_events` with
   the resolved snapshot id. The activate path emits the canonical
   `PathClaimActivated` event.

## Operator surface

Operators do **not** activate claims by hand during normal advance.
This phase owns the flip. The service-client path-claim activation handler is
operator-debug only (mid-implementation amendments, multi-claim coordination)
and has no registered product CLI wrapper; advance preflight performs the
activation unprompted.

The path-claim-required gate
(`yoke_core.domain.path_claim_required_gate.evaluate`) stays a
declaration check, not an acquisition check. The seam between
declaration and acquisition is closed by this phase, not by gate
redefinition.

## Failure behavior

When the phase blocks, the advance command stops without creating a
worktree or mutating status. Surface the blocked or diverged messages
verbatim to the operator and let them decide how to proceed:

- **Blocked claim** — wait for the upstream claim to release. The
  upstream's owning ticket needs to reach a terminal state
  (typically `done`) before activation succeeds.
- **Diverged refs** — reconcile with `git push`, `git pull`, or
  `git rebase` so origin and local agree on `<integration_target>`.

Both are real coordination signals, not paperwork. `--force` does not
override the activation phase; the operator must address the underlying
condition.

---

After the phase passes, return to `SKILL.md` to continue with the
worktree phase.

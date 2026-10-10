# Implement — Worktree Preflight + Re-entry

The implementation-entry engine composes `worktree_preflight.run_preflight`
once: identity probe, claim, path activation, verified upstream and lane.
It emits `AdvancePhaseCompleted{phase="worktree"}`. This is the engine's
contract; normal entry uses [entry.md](entry.md), with no manual relaunch.
Standalone preparation is an operator reconciliation boundary.

The item owns its project and registered checkout; a disagreeing project
cross-check refuses. Same-session claim acquisition is idempotent, a live
holder conflict blocks. A launch-mandated claim already held remains valid.
Write authority is the work-claim, validated per call by `lint_session_cwd`.

## Outcome contract

| Exit | Meaning |
|---|---|
| 0 | JSON envelope: `ok`, `public_ref`, branch/path, `semantic_scope`, `physical_cwd_mode`, actions and notes |
| 1 | Sanctioned block: work/path claim conflict, unreadable or stale upstream, overlapping dirt, creation failure; do not advance |
| 2 | Missing or malformed public item ref |

`physical_cwd_mode=matched` means cwd is inside the lane; `static` means
it stayed at main. Both support writes under the claim.
The canonical first action for sticky-cwd harnesses is the Step 0
`cd` in [Implementation Re-Anchor](implementing/implementation.md#implementation-re-anchor).
Static-cwd tools must inline absolute lane paths and `git -C`; test wrappers
must collect from that lane. Read the project's source-dev and verification
rules before choosing a test invocation.

For known targets, use narrow reads and `rg` with absolute lane paths.
Recursive discovery excludes git, worktrees, caches, virtualenvs, vendored
dependencies and build output. Do not let a main-checkout cwd silently select
another tree.

## Preparation invariants

- Identity is corroborated before mutation. A live work-holder conflict is
  coordination; widening cannot cure it.
- Activation runs once inside preflight; [activation.md](activation.md)
  owns its result. Blocked claims and diverged integration refs propagate.
- Upstream is the project's declared default branch and recorded tracking
  remote, never an assumed name or the checked-out branch. A failed fetch,
  missing tracking remote, unreadable ref or comparison is
  `upstream-unverified`; remote-backed work has no offline fallback.
  A project with no remote is the distinct verified local-only case.
- With verified upstream, a local default with no extra commits can
  fast-forward. Dirt preventing that update, or a default checked out
  elsewhere, stays untouched and the new lane takes the fetched revision.
  Ahead-only local already contains upstream and may start a lane.
  Divergence is `upstream-stale`: preserve and report local commits, never
  reset, replay or rebase them through preparation. Freshness is read per
  preparation, not cached for the whole process. Actions include
  `upstream:<state>`; actionable notes begin `upstream freshness:`.
- Existing canonical lanes are reused without resetting, rebasing or touching
  in-progress work. Reentry still reports freshness.
- Dirty-main checks run only for a new lane. Tracked/staged dirt blocks when
  it overlaps the conflict survey, nonterminal claims or File Budget.
  Untracked, nongitignored files under source/package roots always block;
  repo-root scratch outside those roots is a named warning. Existing lanes
  do not touch main and are not blocked by main dirt.
- Creation provisions the item's own project and records branch, absolute
  path and implementation role in `item_worktrees`. Unresolved project
  refuses. The same session continues into environment/finalize; its claim
  is the authority, not a scope-change event or relaunch.

## Recover a refusal

Surface the narrative verbatim; do not advance status or force/widen past it.
Coordinate with a named work holder, or follow actual dependency direction for
blocked paths using the [claim rules](../../../../.yoke/docs/reference/agent-rules/lanes-and-claims.md).
Only real dependents wait. Ask a dirty-main holder to preserve changes by
commit or correctly named stash; never discard another holder's files.
Restore remote readability for `upstream-unverified`. Diverged commits need
owner reconciliation that preserves them; preparation supplies no automatic
rebase/reset. Surface the git creation error for `worktree-create-failed`.
Retry only after the underlying condition is resolved.

`--no-worktree` is permitted only when explicitly requested by the operator.
It still resolves the claim and activation; the envelope has
`semantic_scope=main`, no cwd mode and `worktree:skipped`. A laneless default
behind its remote (including divergence) blocks as `upstream-stale`;
unverified upstream also blocks. An empty-branch recovery belongs to
[evidence-only.md](evidence-only.md). After `ok=true`, continue the engine's
environment/finalize phases in the same session.

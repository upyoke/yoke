# Path Claims

Path claims are how Yoke answers the question "who may be working
where, and what will they touch?" without needing to inspect every
agent's working tree. A claim names a project-relative surface one of
three explicit owners may mutate (**item**, live **session**, or
**process**), plus integration target and `registered_by_*` provenance.

This document is the operator-facing guide for the everyday
declaration / reconciliation flow. The lifecycle layer's contract
lives in code (`runtime/api/domain/path_claims.py`) and is enforced by
the path-claim API; this doc explains how to use it.

## Operator surfaces

Agents author path-claim mutations through the Yoke function-call surface — the `claims.path.register`, `claims.path.widen`, `claims.path.release`, `claims.path.amend`, and `claims.path.override` function ids (see [`docs/db-reference/functions.md`](db-reference/functions.md)). Operator-facing reads use `yoke claims path get`, `yoke claims path list`, and `yoke path-claims conflicts list`.

Use the wrapped `yoke` adapters for everyday register / read / widen operations:

```
yoke claims path register --item YOK-N --paths a,b,c
yoke claims path list --item YOK-N
yoke claims path get <claim-id>
yoke claims path widen --claim-id <claim-id> --add-paths a,b --reason R --item YOK-N
yoke path-claims conflicts list
```

Break-glass activation, amendment, release, and override surfaces remain command-shaped internal adapters; they are called out below where needed and should not be taught as product wrappers.

### Common subcommands

| Subcommand | Purpose |
|---|---|
| `yoke claims path register --item YOK-N --paths a,b,c [--integration-target T] [--allow-planned]` | Declare a path claim for an item. Resolves paths to canonical `path_targets` rows, runs overlap classification, transitions to `planned` (or `blocked` when a serial-via-dep upstream is named). `--integration-target` defaults to the project trunk (`projects.default_branch`, fallback `main`); pass it explicitly only when gating against a non-trunk branch. Supplied targets that do not resolve to a current git ref reject at registration with a structured error. With `--allow-planned`, paths not yet in the registry are minted as `materialization_state='planned'` rows attributed to the item. |
| `yoke claims path register --item YOK-N --paths "" --mode exception --exception-reason "<why>" [--integration-target T]` | Record a no-claim exception for items that legitimately touch no repo surface (validation tickets, evidence-only items). Pass non-empty `--exception-reason` text so the rendered body can surface the operator's justification verbatim. `--integration-target` defaults to project trunk. |
| `yoke claims path get <claim-id>` | Rich projection: state, declared coverage as readable paths, amendment history, current blocking conflicts. |
| `yoke claims path list --item YOK-N [--state X]` | Same projection, every claim attached to the item, filterable by state. |
| `yoke path-claims conflicts list [--integration-target T]` | Cross-claim conflict listing across the open frontier. |
| Break-glass boundary adapter (`path-claims boundary <claim-id> --repo-path <worktree>`) | Run the committed-git boundary check ad hoc. |
| Break-glass activation adapter (`path-claims activate <claim-id> [--base-snapshot-id N] [--upstream-claim-id N]`) | Acquire the door lock before opening a write surface. Without `--base-snapshot-id`, derives the snapshot from the claim's integration target and the item's project repo. |
| `yoke claims path widen --claim-id N --add-paths a,b --reason R --item YOK-N` | Add new declared coverage. Re-runs overlap classification across the union. |
| Break-glass amendment adapter (`path-claims narrow <claim-id> (--drop-paths a \| --keep-paths a) --reason R --repo-path <worktree>`) | Drop coverage. `--drop-paths` removes the listed paths; `--keep-paths` keeps the listed paths and removes everything else currently on the claim. The flag pair is mutually exclusive at parse time. Runs the boundary check against the proposed new coverage first. |
| Break-glass amendment adapter (`path-claims cancel-amendment <claim-id> --amendment-id N --reason R`) | Append a `cancel` record naming a previous amendment id and reverse its coverage mutation when possible. |
| Break-glass release adapter (`path-claims release <claim-id> --reason R`) | Mark the claim as released — work merged or lineage ended peacefully. |
| Break-glass cancel adapter (`path-claims cancel <claim-id> --reason R`) | Mark the claim as cancelled — lineage abandoned before reaching the integration target. |
Bare `--paths` is rejected on the narrow command; use the explicit keep/drop flags above.

## Boundary check return values

The boundary check (the break-glass `path-claims boundary` adapter and the lifecycle gates at the transitions into `reviewed-implementation`, `implemented`, and `release`) returns one of four statuses:

* **`valid`** — every committed file resolves to declared coverage. Proceed.
* **`drifted`** — declared coverage wider than touched. Not a blocker; release / wait / narrow.
* **`rename_resolved`** — a file moved and the claim covers both old and new paths. Informational.
* **`conflict`** — committed files outside declared coverage, or worktree dirty. The lifecycle gate refuses to advance. Remediate via amend / revert / split, or resolve dirty state.

The check is **committed-only**: uncommitted changes do NOT participate in coverage matching but still block via dirty-state detection.

## When to amend, when to revert, when to split

When the boundary check returns `conflict`, pick the remediation
that matches reality:

| Out-of-coverage commits are… | Action |
|---|---|
| same logical change, no other claim conflicts | **Widen** existing claim |
| same logical change, would conflict with another active claim | **Split** into a new ticket |
| accidental (rebase artifact, debug code, wrong include) | **Revert** the commits |
| different cadence / reviewer / risk profile | **Split** into a new ticket |

* **Widen:** `yoke claims path widen --claim-id <claim-id> --add-paths a,b --reason R --item YOK-N`.
  Re-runs overlap classification on the union; rejects with
  `IncompatibleOverlap` if the union conflicts.
* **Revert:** `git -C <worktree> revert <commit-sha>`; re-run the
  boundary check.
* **Split:** file a new ticket via `/yoke idea`, cherry-pick or
  move the commits onto its branch, register a new claim for that
  coverage, and re-run the original boundary check.

## Narrowing safety

`narrow` runs the boundary check against the *proposed* new coverage
before applying. If the narrow would orphan already-committed work,
it rejects with `NarrowWouldOrphanCommittedWork` and surfaces the
offending paths. Remediation options match the conflict matrix above.
Narrow records the operator's reason on `path_claim_amendments`;
release-and-re-register loses that audit trail.

## Future-path doctrine — claim exact files, not parent directories

The Canonical Path Registry is the single namespace for observed,
planned, and abandoned path identities. Claim **the exact future
path**, not its parent directory:

```
# Right — exact future file, planned target minted:
yoke claims path register \
    --item YOK-N --allow-planned \
    --paths runtime/api/domain/new_module.py

# Wrong — overclaims a directory full of unrelated files:
yoke claims path register \
    --item YOK-N \
    --paths runtime/api/domain/
```

The planned target carries `materialization_state='planned'` until
git observes the file, at which point the snapshot scanner flips
the same row to `observed` and emits `PathTargetMaterialized`. Claim
identity survives the transition. Renames work the same way: claim
the observed source and the planned destination together.

Parent/child overlap (one claim on `a/b/`, another on `a/b/c.py`)
rejects with `IncompatibleOverlap`. Claim narrower or split.

## No-claim exceptions

Validation tickets, evidence-only items, and meta tickets that
legitimately touch no repo surface record a no-claim exception
instead of a normal claim:

```
yoke claims path register \
    --item YOK-N --mode exception \
    --paths "" \
    --exception-reason "validation-only ticket; verifies path-claim coverage end-to-end without code changes"
```

Exceptions land in state `active` immediately (there is no door
lock to acquire), carry zero `path_claim_targets` rows, and surface
in the rendered body as a "No-Claim Exception" block with the
operator's reason verbatim. The catch-up audit and idea/refine gate
both treat a non-terminal exception with non-empty reason as
"coverage satisfied."

## Where the rendered ticket body shows claim state

`yoke items get YOK-N body` renders a
`## Path Claims` section for any item with at least one claim
attached. The section surfaces every claim's id, state, integration
target, actor / session, declared coverage as readable paths,
amendment history, and current blocking conflicts. The rendered
section is GitHub-synced through the existing body-sync path — no
extra command is needed.

## Item terminal transitions

When the owning item reaches a lifecycle terminal, every non-
terminal item-linked claim is auto-finalized via the status-write
chokepoint:

| Item status → | Claim outcome | Reason |
|---|---|---|
| merge-complete `release` | released | `item-release` |
| `done` (backstop) | released | `item-done` |
| `cancelled` | cancelled | `item-cancelled` |
| `stopped` | cancelled | `item-stopped` |

Successful completion uses release semantics (emits
`PathClaimReleased`); abandonment uses cancel semantics (emits
`PathClaimCancelled`). Already-terminal claims are skipped — release
and cancel are idempotent and do not cross-convert.

Some pipelines enter item status `release` before the merge starts so
the item reflects pipeline entry. That pre-merge status write does not
finalize path claims. The automatic `item-release` path only fires for
merge-complete owners (`done-transition` or deploy-pipeline handoff);
`done` remains the universal backstop.

## No-touch-shrink rule

Boundary touch facts never narrow a non-terminal claim. While a
claim is non-terminal, every declared path remains reserved
regardless of whether the worktree has touched it.

If Ticket A actively claims `foo.py` and `bar.py` but only commits
changes to `foo.py`, Ticket B cannot claim `bar.py` merely because
A's diff doesn't touch it. Free `bar.py` for B by (a) narrowing A
explicitly (which runs the boundary check first — see "Narrowing
safety" above) or (b) waiting for A to terminate. Touched files are
an artifact of in-flight work, not a narrowing signal.

## Stale-base-on-new-claim

`widen` runs two distinct safety checks on the truly-new subset:

1. **Overlap classification** — does the union conflict with another
   non-terminal claim? Failure: `IncompatibleOverlap`.
2. **Stale-base-on-new-claim** — has `integration_target` changed
   any newly requested path between the claim's recorded
   `base_commit_sha` and current HEAD? Failure:
   `StaleBaseOnNewClaim` (error_code `stale-base-on-new-claim`).

Stale-base is intentionally a different diagnostic. An overlap is
"two in-flight claims race on the same surface"; a stale-base is
"main moved that file under you, you're claiming on an outdated
view of the world."

| Diagnostic | Remediation |
|---|---|
| `claim_overlap` / `IncompatibleOverlap` | Narrow the holder, declare a serial dependency, wait for release, or use the break-glass path-claim override (last resort) |
| `stale-base-on-new-claim` | Reconcile the working branch with current `integration_target` (rebase or merge), inspect the landed change, then retry the widen |

Stale-base is **not** routed to the break-glass override first — the
operator-collision-approval surface is reserved for true collisions;
an out-of-date base is fixed by syncing the branch.

The comparison anchor is `base_commit_sha` (set at activation),
not git merge-base. The operator-facing widen surface is:

```
yoke claims path widen \
    --claim-id <claim-id> \
    --add-paths new/path.py \
    --reason "follow-up" \
    --item YOK-N
```

The canonical `yoke` command routes through the live function-call
surface and records the amendment against the owning item.

## Resolution tree — when claim coverage collides

When a registration / activation / widen would conflict with another
non-terminal claim on the same integration target, work through this
ordered tree top-to-bottom. Each step is strictly preferred over the
next.

1. **Narrow the over-broad claim explicitly** — use the break-glass
   path-claim amendment adapter from the holder's session when their
   coverage is wider than they need.
2. **Add or verify serial dependency ordering** — register with
   `--upstream-claim-id <holder-id>`; the candidate lands in
   `blocked` and unblocks once the upstream releases.
3. **Wait for release / cancel** — the holder's `release` (or
   `done` backstop) emits `PathClaimReleased` automatically (see
   "Item terminal transitions" above).
4. **Route a narrow / cancel request to the active holder** —
   cross-session emission is deferred to a future ticket; for now
   this collapses to manual operator coordination (reach the holder
   out of band, or escalate to step 5).
5. **Operator override (last resort)** — when normal resolution is
   exhausted, invoke the break-glass override adapter with a non-empty
   `actor_reason`. See below.

**Override is the last resort, never the first move.** Boundary
touch facts never authorize bypassing declared active coverage —
the no-touch-shrink rule applies before, during, and after any
override decision.

### Operator override

Human-only, table-backed (`path_claim_overrides` state rows;
`PathClaimOverride` events are telemetry). Permits a specific
`path_claim_id` to proceed past a specific `blocking_claim_id` for
the named anchor surface. Auto-retires when either participant goes
terminal or the holder narrows the anchors out of its coverage.

```
python3 -m yoke_core.api.service_client path-claim-override <claim-id> \
    --override-point amend \
    --integration-target <project-trunk> \
    --actor-id <operator-actor-id> \
    --actor-reason "<non-empty operator-authored reason>" \
    --blocking-claim-id <blocker-id> \
    --blocking-path-targets <id,id,...>
```

Required: a concrete `<claim-id>` must already exist (no pre-claim
staging) and `actor_reason` must be non-empty.

Override points: `creation` (registration would have failed because
of a live occupancy collision), `amend` (a widen/narrow would have
failed), or `revalidation_conflict` (integration target moved under
an active claim and the conflict cannot be resolved by reconciling;
also pass `--conflict-reason` ∈ {`upstream_delete`,
`hostile_upstream_touch`, `claim_overlap`, `continuity_unknown`}).

Distinct rejection codes: `HOOK_CONTEXT` (`YOKE_HOOK_EVENT` set —
human-only by design), `EMPTY_ACTOR_REASON` (whitespace-only
reason), `CLAIM_NOT_FOUND` (claim id or blocking id does not exist).

Override inserts the `path_claim_overrides` row (the durable fact
the classifier gates on) + WARN telemetry in one transaction. Inspect
the table through a raw diagnostic read only when operator debugging
requires it:

```
yoke db read "SELECT id, path_claim_id, \
    blocking_claim_id, override_point, created_at FROM path_claim_overrides"
```

## Events

Every state change emits a decision-shaped event ledgered in
`events`. Inspect via:

```
yoke events query --event-name PathClaimRegistered --limit 20
yoke events query --event-name PathClaimBoundaryCheckBlocked --limit 20
```

Full event name list: `PathClaimRegistered`, `PathClaimActivated`,
`PathClaimAmended`, `PathClaimReleased`, `PathClaimCancelled`,
`PathClaimOverride`,
`PathClaimRegistrationBlocked`, `PathClaimActivationBlocked`,
`PathClaimAmendmentBlocked`, `PathClaimBoundaryCheckPassed`,
`PathClaimBoundaryCheckBlocked`, `PathTargetPlanned`,
`PathTargetMaterialized`, `PathTargetAbandoned`.

No-claim exceptions reuse `PathClaimRegistered` with envelope
markers `mode='exception'` plus `exception_reason`. There is no
separate `PathClaimException` event.

## Catch-up audit

The path-integrity verifier runs `check_path_claim_coverage` for
every project, flagging any non-terminal issue/epic item that
carries no non-terminal path claim and no active no-claim exception.
Use the `yoke_core.domain.path_integrity` verifier for catch-up
audits; no wrapped product CLI exists for that verifier yet.

The same condition is exposed per-item via the dedicated
`yoke_core.domain.path_claim_required_gate` helper used by
idea/refine skill prose. It returns a structured reason with the
canonical remediation command for skill rendering.

## Activation timing

Operators do **not** activate path claims by hand during `/yoke advance`. The `Phase 1c — Path Claim Activation` step (`runtime/api/domain/advance_path_claim_activation.py`) runs automatically between the path-claim-required gate and the worktree phase, flipping `state='planned'` to `active` for every claim the session owns. Blocked claims stop the advance — that is a real upstream coordination signal. The command-shaped activation adapter remains break-glass only for mid-implementation amendments and is no longer the default.

## Integration target resolution

Canonical SHA for `integration_target="<target>"` is `refs/remotes/origin/<target>` if it exists, otherwise `refs/heads/<target>`. `yoke_core.domain.path_claims_integration_resolver.resolve_integration_head_with_divergence_check` enforces the rule and raises `IntegrationTargetDiverged` when refs have truly diverged. Local-ahead is not divergence.

## Boundary diff anchor — dynamic merge-base

The boundary check diff range is `git merge-base(integration_head, branch_head)..branch_head`. `compute_anchor_sha()` resolves the integration head as the descendant of `origin/<target>` and `refs/heads/<target>` when both exist, so unpushed commits on local main are not false positives, and delegates the merge-base call to `path_claims_boundary_git.merge_base()`. `path_claims.base_commit_sha` is an activation-time audit artifact — recorded for stale-base / age-hint comparisons — but is **not** load-bearing for the boundary diff anchor.

## Operator surface boundary

Everyday reads and mutations use `yoke claims path ...` plus `yoke path-claims conflicts list`. Break-glass activation, amendment, release, and override routes remain command-shaped internal adapters and call the same domain helpers.

## Expressing dependencies between path claims

To express "ticket B waits for ticket A", use the shepherd dependency mutation flow rather than a path-claim-specific command. The path-claim system reads `item_dependencies`: register auto-populates `blocked_reason` so B lands in `state='blocked'` without `--upstream-claim-id`; widen and classify_overlap inherit the same posture in both directions. `--upstream-claim-id` is an advanced escape hatch for multi-claim coordination, not the default. When a claim releases, `propagate_release_unblock` re-classifies downstream blocked claims via direct `blocked_reason` references AND `item_dependencies` satisfaction (`status:done` default), flipping `blocked → planned` automatically.

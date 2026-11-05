# Claims Function Catalog

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Functions](index.md) > Claims
<!-- /yoke:breadcrumbs -->

Read [envelope and authority](index.md) first. `none` means no dispatcher work-claim check; handler permissions still apply. Read command help for the live payload and serving floor.

## Registered functions

| Function id | Claim policy |
|---|---|
| `claims.coordination_claim.acquire` | `none` |
| `claims.coordination_claim.acquire_if_free` | `none` |
| `claims.coordination_claim.heartbeat` | `none` |
| `claims.coordination_claim.list` | `none` |
| `claims.coordination_claim.operator_release` | `steering` |
| `claims.coordination_claim.release` | `none` |
| `claims.path.activation_run` | `item` |
| `claims.path.amend` | `item` |
| `claims.path.boundary_context` | `item` |
| `claims.path.boundary_observe` | `none` |
| `claims.path.boundary_prove` | `item` |
| `claims.path.coordination_decision_build` | `none` |
| `claims.path.get` | `none` |
| `claims.path.list` | `none` |
| `claims.path.override` | `steering` |
| `claims.path.register` | `item` |
| `claims.path.cancel` | `item` |
| `claims.path.release` | `item` |
| `claims.path.required_gate` | `none` |
| `claims.path.survey_ensure` | `item` |
| `claims.path.widen` | `item` |
| `claims.steering.acquire` | `none` |
| `claims.steering.list` | `none` |
| `claims.steering.release` | `self_only` |
| `claims.steering.verify` | `none` |
| `claims.work.acquire` | `none` |
| `claims.work.holder_get` | `none` |
| `claims.work.holder_list` | `none` |
| `claims.work.release` | `self_only` |
| `claims.work.release_session_scoped` | `none` |
| `db_claim.amend` | `item` |
| `decision_requests.create` | `none` |
| `decision_requests.dispose_ended` | `none` |
| `decision_requests.ask` | `none` |
| `decision_requests.list` | `none` |
| `decision_requests.attachment.read` | `none` |
| `decision_requests.get` | `none` |
| `decision_requests.resolve` | `none` |
| `decision_requests.withdraw` | `none` |
| `path_claims.conflicts.list` | `none` |

## Operation obligations

Acquire the assigned item's work claim before its survey or lane preparation.
Release only your own held claim at the authorized handoff. Process claims
resolve project identity to its canonical conflict group on acquisition and
release. Steering scope may be project-wide or paired to one strategy document;
seat/document conflict rolls back both, and release clears the pair together.

Path scope stays complete through conflicts. Registration resolves physical
files and their typed owners; widen before editing an uncovered sibling.
The session holding the work claim attests independent overlaps from its own
skill; when no live holder exists, route to Refine. Overrides need operator authority. See [path claims](../sessions/model/path-claims.md).

Acquire the project deployment coordination claim before creating/executing runs,
heartbeat while driving, release afterward. Stranded holds are human recovery.
Decision requests retain their owning subject, approval posture and exact
candidate evidence; a worker cannot approve its own merge-review request.

DB claim amendment atomically writes mutation profile and compatibility
attestation; reviewed safe claims need their four authored safety fields.
Use the stored-item prose check for relayed diagnostics or its local stdin mode
for intake. Full payload: [items and epics](../items/model/items.md).

Claimless catalog entries still enforce actor/project permissions and ownership.
Read each operation's `--help` before mutation; [envelope](index.md).

A declared DB claim is required when the lane adds numbered migration entries
under any configured `migration_model` history. Refusals name each file and
`yoke db-claim amend PREFIX-N`; spec wording does not trigger this gate.
Release and boot refuse live references to the retired DB claim gate without
changing rows. On the running build, migrate affected items with
`yoke workflows item migrate PREFIX-N` and select clean current versions with
`yoke workflows current set`, then retry. Terminal pins remain historical.

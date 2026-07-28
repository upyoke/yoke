# Workflows

Every Yoke work item is created from a workflow and pinned to one immutable
numbered version. The pin supplies the item's stages, entry checks, execution
posture, registered executors, and allowed per-item tightening. Publishing or
selecting another current version affects new items only.

## Built-in workflows

| Workflow | Use it for | File Budget / path claims | Normal entry |
|---|---|---|---|
| **Dash** | One instruction that can be filed and executed in seconds | optional off / optional off | Web New Item, `yoke dash`, or `/yoke dash` |
| **Blitz** | A substantial document-led plan executed as integrated slices | optional off / optional off | `/yoke idea --workflow blitz "<title>"`, `/yoke refine`, then `/yoke blitz` |
| **Issue** | A bounded change whose item body is the specification | required / required | `/yoke idea`, then refine/advance |
| **Epic** | Work that needs Architect decomposition and task lanes | required per task / required per task | `/yoke idea`, then shepherd/conduct |

Choose the smallest workflow whose structure matches the work. Tightening an
item can independently add File Budget, verification, claims, approval, or
delivery requirements where the workflow allows it. File Budget and path
claims are separate axes: parity applies only when both are enabled. The
350-line authored-file limit is universal even when File Budget is off.
Tightening never removes a workflow gate or core invariant.

## Inspect definitions and item pins

The Workflows screen is the readable operator view. The matching command
surfaces are:

```text
yoke workflows definition get --project <project> --json
yoke workflows item get <PREFIX-N> --project <project> --json
yoke workflows version get <workflow> <version> --json
yoke workflows mechanics get --json
```

The definition read is authoritative for stage ids, display labels, gate
placement, posture, entry surfaces, and current/disabled state. Screens and
operators should not reconstruct those facts from a workflow name.

## Version operations

Published versions are immutable. A policy-default edit publishes a new
version; setting a current version changes only what future items pin.

```text
yoke workflows policy-defaults publish dash \
  --path-claims on --expected-current-version 1

yoke workflows current set dash 2 --expected-current-version 1
```

Moving an existing item is explicit and compatibility-checked:

```text
yoke workflows item migrate <PREFIX-N> --version 2 --project <project>
```

Migration permits label-only and otherwise semantically compatible changes.
It refuses a target that cannot preserve the current stage and posture, active
lane roles, claim ownership scope, approval or QA transition gates, or delivery
action semantics. A target also cannot add an unsatisfied approval or QA gate
at a stage the item has already reached. Rejection happens before the pin or
status is written. Selecting an older version as current is a rollback for new
work, not a silent rewrite of active work.

## Project mechanics

Testing and delivery defaults are project-owned. Approval defaults are
universe-owned workflow policy and publish a new version.

```text
yoke workflows testing-default set \
  --project <project> --workflow issue --plan-id <plan-id>

yoke workflows delivery-default set \
  --project <project> --workflow issue --flow <flow-id>

yoke workflows approval-defaults publish \
  --workflow issue --expected-current-version <version> \
  --defaults-file <json-file>
```

An item may still carry a permitted tighter posture or an explicit delivery
flow. Delivery timing remains structural: the workflow's stages decide when
delivery happens.

## Dash

The browser and the CLI file a Dash; they do not execute it:

```text
yoke dash "<title>" "<instruction>" --project <project>
```

In a harness, `/yoke dash "<instruction>"` files and executes a new Dash, and
`/yoke dash <PREFIX-N>` resumes an existing one. Dash execution surveys
coordination state, isolates work in a registered worktree, verifies, merges,
and records evidence. Registered path claims always win over claim-less Dash
work. If the instruction grows into planned or multi-slice work, Dash records
the findings, creates an Issue through normal intake, links it, and cancels.

## Blitz

A Blitz links exactly one execution strategy document. The document remains
the live plan, progress log, handoff surface, evidence summary, completion
record, and parent-reconciliation record; the item holds system facts.

Create it through the explicit typed intake route:

```text
/yoke idea --workflow blitz "<title>"
```

That harness route dispatches registered function id `items.create` with
`workflow: "blitz"` and `entry_surface: "harness_skill"`. The created item
starts at `idea`; it is not executable yet. Run `/yoke refine <PREFIX-N>` so
refinement links exactly one execution strategy document and advances the item
to `refined-idea`.

Use `/yoke blitz <PREFIX-N>` only after that document link exists. The skill
acquires the item-owned document claim, surveys coordination state, executes
coherent slices in registered worktree lanes, updates the document after
integration, and closes only after verification and reconciliation are
recorded. Do not copy the plan into the item body or generate child items.

The document claim survives session handoff. Only the session holding the
Blitz item claim may revise plan content; append-only Slice Log and Live Status
updates remain available for coordination.

## Related guides

- [Testing and verification](testing-verification.md)
- [Path claims](path-claims.md)
- [State management](state-management.md)

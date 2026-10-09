# Workflows Function Catalog

Read [envelope and authority](functions.md) first. `none` means no dispatcher work-claim check; handler permissions still apply. Read command help for the live payload and serving floor.

## Registered functions

| Function id | Claim policy |
|---|---|
| `advance.preflight.file_budget` | `none` |
| `advance.preflight.hard_blocks` | `none` |
| `advance.preflight.spec_coverage` | `none` |
| `charge.schedule` | `none` |
| `direct_workflow.blitz.survey` | `none` |
| `direct_workflow.conflict_survey.status` | `none` |
| `direct_workflow.dash.escalate` | `item` |
| `direct_workflow.dash.evidence` | `item` |
| `direct_workflow.dash.survey` | `none` |
| `frontier.list` | `none` |
| `gate_satisfier.rung.resolve` | `none` |
| `shepherd.caveat_disposition.run` | `none` |
| `shepherd.verdict.run` | `none` |
| `workflow.execution_instruction.create` | `none` |
| `workflow.execution_instruction.delete` | `none` |
| `workflow.execution_instruction.list` | `none` |
| `workflow.execution_instruction.resolve` | `none` |
| `workflow.execution_instruction.set_scope` | `none` |
| `workflow.execution_instruction.update` | `none` |
| `workflows.approval_defaults.publish` | `none` |
| `workflows.canon.get` | `none` |
| `workflows.canon_follow.set` | `none` |
| `workflows.canon_status.list` | `none` |
| `workflows.canon_update.apply` | `none` |
| `workflows.canon_update.apply_all` | `none` |
| `workflows.canon_update.preview` | `none` |
| `workflows.current.set` | `none` |
| `workflows.definition.get` | `none` |
| `workflows.delivery_default.set` | `none` |
| `workflows.item.get` | `none` |
| `workflows.item.migrate` | `steering` |
| `workflows.item_posture.amend` | `item` |
| `workflows.mechanics.get` | `none` |
| `workflows.policy_defaults.publish` | `none` |
| `workflows.testing_default.set` | `none` |
| `workflows.version.get` | `none` |
| `workflows.version.list` | `none` |
| `workflows.version.publish` | `none` |

## Immutable pins and routing

Definition reads return versions, gates and flow metadata. Item reads return
the exact pin/digest, live stage, effective policies and lanes. Selecting the
current version affects later creates; existing pins never move implicitly.
Migration requires operator authority and preserves representable stages,
lanes/claims, approvals, QA and delivery bindings; retroactively unsatisfied
gates refuse. Read the live half-open binding before dispatching a skill.

Posture amendment changes one allowlisted key with its declared guard. Refuse
terminal state, an executed verification selection, registered claims under a
selection being cleared, or an open owner decision for cleared approval.
Replacement atomically waives unexecuted superseded requirements, detaches the
old plan and attaches the new one. A key without a guard is unamendable.

## Published canon updates

A `workflows.version.publish` write takes the full `definition`, `workflow_id`,
`reason`, optional `expected_current_version` and `keep_current`. Existing ids
require the expected version; new ids omit it. Publication appends immutable
content and actor/reason audit. Default selects it and disables canon following;
append-only keeps current/follow unchanged. Existing item pins never move.
Receipt: `workflow_id`, `version`, `version_id`, `definition_digest`, `current`.

A universe's workflow version number is local; canon standing compares digests.
Global status lists published workflows, current/latest canon, following mode,
pending changes and the four states: `up_to_date`, `update_available`,
`customized`, `customized_update_available`. Pending-only selects update states;
local workflows without canon are absent.

Status rows retain `workflow_id`, `name`, `current_version`, `state`, `follow`,
`latest_canon_version`, `pending`, and `current_canon_version` or
`derived_from_canon_version`. Apply receipt retains `workflow_id`, `version`,
`version_id`, `definition_digest`, `canon_version`, `taken`, `kept`. Apply-all
takes `workflows: [{workflow_id, expected_current_version}, ...]` and returns
independent `applied` receipts or `refused` rows with id/code/message. Follow
returns `workflow_id`, `follow`, `previous_follow`; all use a global target.

Preview computes taken/kept/conflicts and merged definition without publishing;
up-to-date or canon-less subjects refuse. Apply takes the newest generation with
`expected_current_version`, preserves local edits, and publishes or selects an
existing matching definition. Conflicts refuse with exact paths. Apply-all
attempts each unique workflow independently: committed successes remain when
another refuses; duplicate subjects refuse. Its nonzero exit reports any refusal.

Follow selects auto/manual and returns previous mode. Local edits or selecting
older generations turn following off; only explicit follow turns it on again.
That write adopts nothing until boot or explicit apply. Writes require org admin;
below-floor clients receive the named function-version refusal.

```text
yoke workflows version publish WORKFLOW --definition-file F --reason TEXT --expected-current-version {version} --json
yoke workflows canon-status list --pending --json
yoke workflows canon-update preview WORKFLOW --json
yoke workflows canon-update apply WORKFLOW --expected-current-version N --json
yoke workflows canon-update apply-all WORKFLOW=VERSION --json
yoke workflows canon-follow set WORKFLOW auto --json
```

Direct workflow/frontier/authoring entrypoints use the same pinned policy facts;
they never replace a work claim or bypass the next binding's fresh handoff.

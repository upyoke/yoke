# Dash — registered operation authority

Read this when you need the function id or exact adapter shape for a Dash
operation, not as a phase step. Every `yoke` command in the Dash phase files
is a CLI adapter for the same function-call envelope; the function id is the
operation authority.

| Function id | Target and payload | CLI adapter |
|---|---|---|
| `items.create` | Global target; Dash title, instruction, project, entry surface, permitted posture, and the operator execution-instruction attestation | `yoke dash "<title>" "<instruction>" --execution-instructions-considered --json` |
| `workflow.execution_instruction.resolve` | Global target; named workflow and project; read-only matching instructions | `yoke workflow execution-instruction resolve --workflow W --project P` |
| `items.detail.get` | Item target; optional `include` naming content sections (`narrative`, `body`, `progress_log`) — omit for the posture plus `content_index`, which names each stored section and the read that returns it | `yoke items detail get ITEM --json` |
| `github.merge_queue.readiness` | Item target; empty payload; reads PR and target-branch queue without mutation | `yoke github merge-queue readiness ITEM --json` |
| `github.merge_queue.hold` | Item target; empty payload; clears merge-when-ready, removes the queue entry, and verifies both before a correction is pushed | `yoke github merge-queue hold ITEM --json` |
| `claims.work.acquire` | Item target; `reason` | `yoke claims work acquire --item ITEM --reason TEXT` |
| `workflows.item.get` | Item target; empty payload; centrally resolved effective policies | `yoke workflows item get ITEM --json` |
| `items.structured_field.section_upsert` | Item target; a posture-enabled File Budget section | `yoke items structured-field section-upsert ITEM --section "File Budget" ...` |
| `direct_workflow.dash.survey` | `paths` or explicit `no_changes`, plus optional `integration_target` | `yoke direct-workflow dash survey ITEM (--path PATH \| --no-changes) --json` |
| `direct_workflow.conflict_survey.status` | Item target; empty payload — rediscover the live survey | `yoke direct-workflow conflict-survey status ITEM --json` |
| `claims.path.register` | Item target; complete paths plus mode and optional planned/exception posture | `yoke claims path register --item ITEM --paths PATHS ...` |
| `qa.plan.materialize` | Item target; the transition whose attached plans become case rows | `yoke qa plan materialize --item ITEM --transition T --json` |
| `qa.requirement.list` | Item target; empty payload — the materialized requirement ids | `yoke qa requirement list --item ITEM --json` |
| `qa.requirement.add` | Item target; selected method, executable case contract, and workflow transition | `yoke qa requirement add --item ITEM ...` |
| `lifecycle.transition.execute` | Item target; `source_status`, `target_status`, and `reason` | `yoke lifecycle transition ITEM --from STATUS --to STATUS --reason TEXT` |
| `deployment_runs.start_for_item` | Item target; selected/default flow and merged release lineage | `yoke --env <control-plane> deployment-runs start-for-item ITEM ...`; use paired `*-db-admin` only for a serving-API self-deploy |
| `direct_workflow.dash.evidence` | `result_summary`, `verification_summary`, `verification_status`, `commit_sha`, `merge_sha`, `touched_files`, and `no_changes` | `yoke direct-workflow dash evidence ITEM ...` |
| `claims.work.release` | Current item or claim target; `reason` | `yoke claims work release --item ITEM --reason TEXT` |
| `direct_workflow.dash.escalate` | `issue_title`, `findings`, and optional `priority` | `yoke direct-workflow dash escalate ITEM ...` |

## Who may call what

Survey has no item-claim precondition. Evidence, escalation, lifecycle
transitions, and path-claim registration all require the current item claim.
Work-claim release is self-only.

## The two tool-shaped operations

Worktree preparation and merging are each a retained tool-shaped operation,
because both act on the local checkout rather than on control-plane state
alone. Each command has no registered `direct_workflow.*` function id — use
them verbatim; do not invent function ids for them.

```text
yoke direct-workflow worktree prepare ITEM --workflow dash --json
yoke merge item ITEM --result "<what changed>" --verification "<checks run>"
```

The first delegates to the local engine worktree preflight. The second is the
standalone-item merge boundary: it takes the merge lock, lands the branch on
the project base branch, stamps `merged_at`, publishes, records execution
evidence with the merge identity it just resolved, and then transitions the
item — through the `dash_evidence` gate, not around it. Run
`yoke merge item --help` for the flag matrix, and see
[`docs/archive/decisions/standalone-item-merge.md`](../../../../docs/archive/decisions/standalone-item-merge.md)
for the contract.

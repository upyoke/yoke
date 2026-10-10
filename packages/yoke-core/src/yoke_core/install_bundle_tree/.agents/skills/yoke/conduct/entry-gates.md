# Conduct — entry contract

Require a complete public PREFIX-N. Missing ref stops with
`Missing required argument. Usage: /yoke conduct PREFIX-N`.

| Flag | Meaning |
|---|---|
| --max-attempts N | Total Engineer/Tester cycles; default 5. |
| --no-chain | Stop after the current generated task; preserve the remainder. |
| --force / --ignore-gaps | Explicit simulation-gap override; same flag semantics. |
| --no-auto-fix | Halt on unresolved integration gaps instead of automatic fix. |

## Pin, authority and independent scope axes

```text
yoke workflows item get PREFIX-N --json
yoke workflows version get WORKFLOW {version} --json
```

Read workflow_id, workflow_version and status from the first result; select
the second definition's skill_bindings row whose ordered stages satisfy
from_stage_id ≤ live stage < through_stage_id. Terminal stops. Missing/unreadable
pin, stage or ambiguous binding halts as conduct_binding_unavailable with the
named fact to repair. Another skill halts as conduct_skill_not_bound; use its
rendered entrypoint. At through_stage_id refresh the pin and hand off.

Read effective_policies.file_budget and .path_claims independently: required
means item scope, required_per_task means generated-task scope, optional is off.
Only enabled axes require their artifacts. Claims on/budget off derives paths
from task scope and survey; budget on/claims off remains sizing/conflict
evidence. Pair only when both on; neither axis narrows required scope. Every
posture retains the universal 350-line authored-file ceiling and receipt.
Task/lane shape comes from policies.generated_children and .worktrees.

## Before dispatch

Obey the fetched Workflow Execution Instructions before item prose.
Read structured spec, with body only when spec is absent:

```text
yoke items get PREFIX-N spec
yoke items get PREFIX-N body
```

Require canonical unchecked AC rows or checkboxes under Acceptance Criteria.
Absent ACs halt as acceptance_criteria_missing; detail resolves the pinned
authoring binding for repair. Do not dispatch an undefined task.

Activation dependencies alone gate dispatch; integration/closure belong to
downstream landing/completion. The retained source-dev checker is scoped:

```text
python3 -m yoke_core.domain.check_hard_blocks PREFIX-N --gate-point activation
yoke items dependency list PREFIX-N
```

Capture the checker, preserve its nonzero exit and BLOCKED ref/status/title
diagnostics; HALT with unresolved activation dependencies. Do not hide stderr
or infer success from missing output. Recheck the live binding if stage changes.

Next: [entry-activation.md](entry-activation.md).

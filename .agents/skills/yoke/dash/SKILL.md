---
name: dash
description: "File or execute instruction-sized Dash work through survey, isolation, verification, merge, and evidence."
argument-hint: "\"instruction\" | {PREFIX-N}"
---

# /yoke dash

Execute one instruction-sized work item end to end. A new instruction is
filed and executed immediately; an item reference resumes an existing Dash.
Dash uses ordinary item, claim, worktree, lifecycle, QA, merge, and
deployment surfaces. It does not route through `/yoke idea`.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Registered operation authority

Use the registered function id as the operation authority. The `yoke`
commands shown throughout this skill are CLI adapters for the same
function-call envelope:

| Function id | Target and payload | CLI adapter |
|---|---|---|
| `items.create` | Global target; Dash title, instruction, project, entry surface, and permitted posture | `yoke dash "<title>" "<instruction>" --json` |
| `items.detail.get` | Item target; empty payload | `yoke items detail get ITEM --json` |
| `workflows.item.get` | Item target; empty payload; centrally resolved effective policies | `yoke workflows item get ITEM --json` |
| `items.structured_field.section_upsert` | Item target; a posture-enabled File Budget section | `yoke items structured-field section-upsert ITEM --section "File Budget" ...` |
| `direct_workflow.dash.survey` | `paths` plus optional `integration_target` (defaults to `main`) | `yoke direct-workflow dash survey ITEM --path PATH --json` |
| `claims.path.register` | Item target; complete paths plus mode and optional planned/exception posture | `yoke claims path register --item ITEM --paths PATHS ...` |
| `qa.requirement.add` | Item target; selected method, executable case contract, and workflow transition | `yoke qa requirement add --item ITEM ...` |
| `lifecycle.transition.execute` | Item target; `source_status`, `target_status`, and `reason` | `yoke lifecycle transition ITEM --from STATUS --to STATUS --reason TEXT` |
| `deployment_runs.start_for_item` | Item target; selected/default flow and merged release lineage | `yoke deployment-runs start-for-item ITEM ...` |
| `direct_workflow.dash.evidence` | `result_summary`, `verification_summary`, `verification_status`, `commit_sha`, `merge_sha`, `touched_files`, and `no_changes` | `yoke direct-workflow dash evidence ITEM ...` |
| `claims.work.release` | Current item or claim target; `reason` | `yoke claims work release --item ITEM --reason TEXT` |
| `direct_workflow.dash.escalate` | `issue_title`, `findings`, and optional `priority` | `yoke direct-workflow dash escalate ITEM ...` |

Survey has no item-claim precondition; evidence and escalation require the
item claim. Lifecycle transitions and path-claim registration also require
the current item claim; work-claim release is self-only.

Worktree preparation is intentionally a retained tool-shaped operation:

```text
yoke direct-workflow worktree prepare ITEM --workflow dash
```

It delegates to the local engine worktree preflight and has no registered
`direct_workflow.*` function id. Use the command verbatim; do not invent a
function id for it.

## Inputs

- `/yoke dash "instruction"` — author a concise title, file the Dash, and
  execute it in this session.
- `/yoke dash PREFIX-N` — execute the already-filed Dash.

`yoke dash "title" "instruction"` is the non-harness filing adapter. It
files and prints the item; it does not execute it.

## Invariants

- Treat the stored instruction as the complete requested scope.
- Perform all writes in the registered item worktree, never in main.
- Registered work and path claims always win over claim-less Dash work.
- Do not create child items. If the instruction has grown into planning or
  multi-slice work, use the escalation operation, which records the
  findings, files one Issue through normal intake, links it, and cancels
  the Dash.
- Consume the central `workflows.item.get` effective-policy projection before
  authoring or gating File Budget and path claims. Each axis remains
  independent; do not reconstruct it from raw policies or posture.
- Honor every selected item-posture knob. Posture can tighten execution; it
  cannot remove a workflow gate or a governed migration invariant.
- Do not transition to `done` until the branch is merged and the evidence
  record contains the result, passing verification, merge identity, and
  touched files, and every selected posture passes its real authority gate.

## Execute

### 1. Resolve or file

If the argument is not an item reference:

1. Write a specific title of at most 100 characters.
2. File with:

   ```text
   yoke dash "<title>" "<instruction>" --json
   ```

3. Keep the returned item reference as `ITEM`.

If the argument is a reference, use it as `ITEM`. Read the item detail and
workflow-effective projections:

```text
yoke items detail get ITEM --json
yoke workflows item get ITEM --json
```

Require `workflow_id=dash`, status `idea` or a resumable Dash stage, and
retain the stored instruction. Set `FILE_BUDGET_POLICY` and
`PATH_CLAIMS_POLICY` from
`result.effective_policies.file_budget` and
`result.effective_policies.path_claims` in `workflows.item.get`.
`required` is on at item scope, `required_per_task` is on at generated-task
scope, and `optional` is off. The runtime projection owns historical
compatibility and allowed posture tightening.
The 350-line authored-file limit remains on in all combinations.

### 2. Infer and survey the touch set

Read the repository just far enough to name the files or directories the
instruction is likely to touch. Prefer file paths; use a directory only
when the instruction genuinely spans that directory.

Record the survey:

```text
yoke direct-workflow dash survey ITEM --path <path> [--path <path> ...] --json
```

When `FILE_BUDGET_POLICY` is non-`optional`, persist the surveyed edit targets and their
single responsibilities under `## File Budget` through
`items.structured_field.section_upsert` before implementation. When disabled,
do not require or invent the section. When `PATH_CLAIMS_POLICY` is
non-`optional` and budget is
off, the survey itself is the claim-path source. When both are enabled, pair
their enumerations. When budget is on and claims are off, use the budget for
sizing and conflict evidence without registering a claim.

For every reported contact:

- yield to active or planned registered claims;
- coordinate with the owning item or wait when the scope is still small;
- when effective path claims are enabled, keep the inferred set complete;
  worktree preparation registers or widens the real claim from this survey;
- if contact repeats or the required work is no longer instruction-sized,
  follow **Escalate** below.

Never remove a required file merely to make the survey clear.

### 3. Claim and isolate

Prepare the ordinary item lane:

```text
yoke direct-workflow worktree prepare ITEM --workflow dash
```

Use the returned absolute `worktree_path` for every read, edit, test, and
git command. The preparation call acquires the item work claim, registers
or widens selected path claims from the non-empty survey, activates them,
and creates or reuses the registered worktree.

Activate through the shared lifecycle interpreter:

```text
yoke lifecycle transition ITEM --from idea --to implementing --reason "Dash execution started"
```

The transition must pass the live `conflict_survey` gate and the
`work_claim_activation` gate, which verifies that this session owns the
active item claim and that the item has its registered implementation
worktree. A stale or newly-blocked survey is a coordination stop, not a
bypass candidate.

### 4. Execute the instruction

Make the smallest complete change. Preserve unrelated work. Apply the
repository's simplify doctrine and governed database rules. Run focused
checks while editing. Capture every non-trivial test or build before
inspecting its tail.

If the instruction is investigative, the durable result may be a
well-grounded no-change finding. Do not invent a code change merely to
produce a diff.

### 5. Verify and close review

Run the relevant project verification and an agent self-check. Then execute
each selected posture knob through its shared authority:

- `verification.kind=plan` — materialize the attached plan cases for
  `reviewing-implementation`, execute each requirement with
  `yoke qa case run --requirement-id <id>`, and retain passing runs.
- `verification.kind=ad_hoc` — author the concrete selected-method case from
  the stored instruction and actual target, then execute the returned
  requirement:

  ```text
  yoke qa requirement add --item ITEM \
    --method-id <stored-method-id> --qa-phase verification \
    --workflow-transition reviewing-implementation \
    --instructions "<instruction applied to the actual target>" \
    --expected-outcome "<observable passing result>" \
    --method-config '<method-specific JSON>'
  yoke qa case run --requirement-id <requirement-id>
  ```

- `file_budget` — when selected, confirm the persisted budget covers actual
  edit targets and remains useful sizing/conflict evidence;
- `path_claims` — when selected, the lifecycle gate requires active concrete coverage now
  and compares the merged touched-file evidence with that coverage at done.
- `approval_on_done` — the final transition creates a project-owner decision
  request and stays blocked until an authorized owner approves it.
- `deployment` — after merge, run the selected/default item-bound project
  flow for the recorded merge identity and wait for status `succeeded`.

Move into the verification-close stage only when implementation checks
pass:

```text
yoke lifecycle transition ITEM --from implementing --to reviewing-implementation --reason "Implementation complete; verification passed"
```

### 6. Re-survey actual files and merge

Resolve the exact touched set from the worktree diff. Re-run the survey
with every actual file immediately before merge:

```text
yoke direct-workflow dash survey ITEM --path <actual-file> [--path <actual-file> ...] --json
```

If the result is blocked, do not merge. Coordinate, wait, tighten with
claims, or escalate. When clear, commit the coherent change and merge the
registered branch through the project's normal protected merge path. Do
not force-push, bypass CI, or merge around a registered claim. Record both
the implementation commit SHA and resulting merge SHA.

For a verified no-change result, use the inspected base SHA for both
identities and set `--no-changes`; no empty commit is needed.

### 7. Record evidence and finish

When deployment posture is selected, start item-bound delivery for the merge
identity and run the returned deployment through the project executor:

```text
yoke deployment-runs start-for-item ITEM \
  --release-lineage <merge-sha> --json
```

Wait for that item-bound run to reach `succeeded`. Then record the close:

```text
yoke direct-workflow dash evidence ITEM \
  --result "<what changed or was learned>" \
  --verification "<checks and evidence>" \
  --commit-sha <sha> --merge-sha <sha> \
  --path <actual-file> [--path <actual-file> ...]
```

Use `--no-changes` instead of `--path` only for a genuine no-change result.
Then transition through the `dash_evidence` gate:

```text
yoke lifecycle transition ITEM --from reviewing-implementation --to done --reason "Merged and evidence recorded"
```

When approval-on-done is selected, the first attempt creates the owner
decision request without moving the item. Let an authorized owner resolve it,
then retry the same transition. The successful terminal transition releases
the registered Dash worktree lane. Finally release the item work claim:

```text
yoke claims work release --item ITEM --reason "Dash completed"
```

## Escalate

Escalate as soon as the required outcome needs crafted acceptance criteria,
substantial design, durable multi-file coordination, or multiple delivery
slices. Summarize what was discovered and the remaining work:

```text
yoke direct-workflow dash escalate ITEM \
  --issue-title "<specific title>" \
  --findings "<grounded findings and remaining outcome>"
```

The operation is idempotent: it preserves one link to the absorbing Issue
and cancels the Dash. Stop Dash execution after it succeeds and release the
work claim if the operation did not already do so.

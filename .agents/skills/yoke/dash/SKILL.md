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
| `items.create` | Global target; Dash title, instruction, project, entry surface, permitted posture, and the operator execution-instruction attestation | `yoke dash "<title>" "<instruction>" --execution-instructions-considered --json` |
| `workflow.execution_instruction.resolve` | Global target; named workflow and project; read-only matching instructions | `yoke workflow execution-instruction resolve --workflow W --project P` |
| `items.detail.get` | Item target; empty payload | `yoke items detail get ITEM --json` |
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
| `deployment_runs.start_for_item` | Item target; selected/default flow and merged release lineage | `yoke --env <control-plane>-db-admin deployment-runs start-for-item ITEM ...` |
| `direct_workflow.dash.evidence` | `result_summary`, `verification_summary`, `verification_status`, `commit_sha`, `merge_sha`, `touched_files`, and `no_changes` | `yoke direct-workflow dash evidence ITEM ...` |
| `claims.work.release` | Current item or claim target; `reason` | `yoke claims work release --item ITEM --reason TEXT` |
| `direct_workflow.dash.escalate` | `issue_title`, `findings`, and optional `priority` | `yoke direct-workflow dash escalate ITEM ...` |

Acquire the item work claim first, immediately after the item reference is
known — it is the session's authority over the item and its worktree for the
whole Dash. Survey has no item-claim precondition, but evidence and
escalation require the item claim. Lifecycle transitions and path-claim
registration also require the current item claim; work-claim release is
self-only.

Worktree preparation and merging are each a retained tool-shaped operation,
because both act on the local checkout rather than on control-plane state
alone:

```text
yoke direct-workflow worktree prepare ITEM --workflow dash --json
yoke merge item ITEM --result "<what changed>" --verification "<checks run>"
```

The first delegates to the local engine worktree preflight. The second is the
standalone-item merge boundary: it takes the merge lock, lands the branch on
the project base branch, stamps `merged_at`, publishes, records execution
evidence with the merge identity it just resolved, and then transitions the
item — through the `dash_evidence` gate, not around it. Each command
has no registered `direct_workflow.*` function id — use them verbatim; do
not invent function ids for them. Run
`yoke merge item --help` for the flag matrix, and see
[`docs/archive/decisions/standalone-item-merge.md`](../../../../docs/archive/decisions/standalone-item-merge.md)
for the contract.

## Inputs

- `/yoke dash "instruction"` — author a concise title, file the Dash, and
  execute it in this session.
- `/yoke dash PREFIX-N` or `/yoke dash N` — execute the already-filed Dash.
  A bare number resolves as the current project's public item sequence. Do not
  invent or guess a prefix; pass the operator's token through unchanged.

`yoke dash "title" "instruction" --execution-instructions-considered` files
without executing; use `yoke task "title" "instruction" --execution-instructions-considered`
for the laneless, merge-free alternative with no optional gate posture.

## Invariants

- Treat the stored instruction as the complete requested scope.
- Obey the `# Workflow Execution Instructions` operator block at the top of
  fetched item content; it layers on top of, and never replaces, the item's
  own stored instruction and spec.
- Acquire the item work claim as the first action once the item reference
  exists, and hold it through the Dash. A successful standalone merge or
  terminal transition may already release the claim and remove the lane —
  only call `claims.work.release` when a claim remains, or when exiting
  before merge (including escalation). This mirrors `/yoke idea` and
  `/yoke refine` on acquire; release is conditional on what close-out
  already did.
- Perform all writes in the registered item worktree, never in main.
- An item belonging to another project prepares its lane in THAT
  project's checkout: worktree preparation resolves the item's project
  machine mapping (`yoke project register <checkout> --project-id <id>`
  adds a missing one) and refuses rather than borrowing the session's
  repo. The work claim covers the recorded lane; repair a wrong-repo
  lane with `yoke item-worktrees path-record`. One item never gets a
  second lane in another repo. Work the instruction turns out to
  mandate in a second project needs its own companion item filed
  there and linked by an `item_dependencies` edge — a scope judgment
  the operator owns, so follow **Escalate** below rather than writing
  into that repo from here.
- Survey contacts are advisories: proceed or yield after reading each one.
- Do not create child items. If the instruction has grown into planning or
  multi-slice work, halt and discuss escalation with the operator. Escalation
  files one Issue through normal intake and cancels the Dash, so the decision
  to escalate belongs to the operator, not to this session. This halt is a
  deliberate exception to the kick-off-and-walk-away default: escalation
  creates a new work item and is a scope judgment, not routine execution.
  Only run the escalation operation after the operator explicitly agrees.
- Consume the central `workflows.item.get` effective-policy projection before
  authoring or gating File Budget and path claims. Each axis remains
  independent; do not reconstruct it from raw policies or posture.
- Honor every selected item-posture knob. Posture can tighten execution; it
  cannot remove a workflow gate or a governed migration invariant.
- Do not transition to `done` until the branch is merged and the evidence
  record contains the result, passing verification, merge identity, and
  touched files, and every selected posture passes its real authority gate.

## Execute

Stamp the session mode first so the board's active-session row reflects the
live phase (the default `wait` misrepresents an active Dash):

```text
yoke sessions touch --mode dash
```

### 1. Resolve or file

If the argument is not an item reference:

1. Resolve the target project as `PROJECT`; the workflow is `dash`.
2. Before authoring the title or changing the supplied instruction, read the
   registered `workflow.execution_instruction.resolve` projection and obey
   every matching instruction:

   ```text
   yoke workflow execution-instruction resolve --workflow dash --project PROJECT
   ```

3. Write a specific title of at most 100 characters.
4. File with, passing `--execution-instructions-considered` to attest the
   read in step 2 (the create refuses without it, and no adapter sets it
   for you):

   ```text
   yoke dash "<title>" "<instruction>" --execution-instructions-considered --json
   ```

3. Keep the returned item reference as `ITEM`.

If the argument is a reference, use it as `ITEM`.

**Claim the item first.** As soon as `ITEM` is known — whether just filed or
resumed — acquire the item work claim before any survey, budget, path, or
edit work. The claim is the session's authority over the item and its
worktree; hold it for the whole Dash. This mirrors `/yoke idea` and
`/yoke refine`, which claim before touching any shared state:

```text
yoke claims work acquire --item ITEM --reason "Dash execution"
```

For a launched worker this is survival, not just order. A session holding no
claim is what the non-destructive session end reaps as idle, so a worker that
surveys before it claims can be ended mid-mandate: one spent 79 tool calls
reading the codebase, was auto-ended claim-free, and left its item looking
untouched. Claim before the first read, and that reaping becomes structurally
impossible.

Then read the item detail and workflow-effective projections:

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

Discover this project's source and test roots before grepping — read them
from the project rules file, or derive tracked top-level roots with
`git ls-files | cut -d/ -f1 | sort -u`. Enumerate candidates from those
resolved roots with `rg --files ... | rg '<name-or-symbol>'` before reading;
never pass optional path globs to zsh, invent a conventional source root, or
mirror a test filename into an assumed implementation path. Use imports or
symbols to find the owner. Then read only far enough to name the likely touch
set. Prefer files; use a directory only when the work genuinely spans it.

Record the survey:

```text
yoke direct-workflow dash survey ITEM --path <path> [--path <path> ...] --json
yoke direct-workflow dash survey ITEM --no-changes --json
```

Use the second, empty-intent form only for a grounded no-change outcome. The
forms are exclusive; never invent a placeholder path for a no-change Dash.

Every survey call replaces the entire stored touch set; it never widens the
previous set. Repeat every still-required path on every call. To rediscover
the live survey at path-widening time, run
`yoke direct-workflow conflict-survey status ITEM --json` — there is no
`yoke survey` command. The receipt names this as
`touch_path_update="replace"` and echoes the complete stored set.

The response's `path_sizes` carries `current_line_count`,
`remaining_headroom`, `at_or_over_limit`, `limit`, and `classification` for
every path. Treat an at/over-limit path as a pre-implementation split or
alternate-home decision; do not wait for the commit gate.

When `FILE_BUDGET_POLICY` is non-`optional`, persist the surveyed edit targets and their
single responsibilities plus the survey's same per-path sizing fields under `## File Budget` through
`items.structured_field.section_upsert` before implementation. When disabled,
do not require or invent the section. When `PATH_CLAIMS_POLICY` is
non-`optional` and budget is
off, the survey itself is the claim-path source. When both are enabled, pair
their enumerations. When budget is on and claims are off, use the budget for
sizing and conflict evidence without registering a claim. When both are off,
the stored instruction and survey define scope without either artifact.

For every reported survey contact, read the advisory and choose:

- proceed when the edits are independent; same-file collisions resolve at merge;
- when the decision needs holder evidence, ask an addressable holder for that
  evidence with the harness task-messaging tool (`send_message_to_thread` in
  Codex). When the holder is not addressable in the current harness, give the
  operator its session id and wait;
- when the edits are order-dependent, wait for the holding work to land
  (merge receipt, merged_at, or git ancestry — not status) and re-run the survey;
- when a directory survey was only a discovery aid, narrow it to the complete
  concrete file set before preparation, repeating every required file in the
  replacement survey;
- when an overlap cannot be decided or resolved from the surfaced evidence,
  release the work claim and present the holder, paths, and evidence to the
  operator; do not create a dependency or attestation, or continue editing
  through uncertainty;
- if the required work is no longer instruction-sized,
  stop and follow **Escalate** below, which halts for operator agreement
  before anything is filed.

Selected path-claim posture is a separate coverage obligation, never a remedy
for a survey contact. When effective path claims are enabled, keep the inferred
set complete and register or widen it through `claims.path.register` /
`claims.path.widen` before preparation; preparation only validates that
coverage.

Never remove a required file merely to make the survey clear.

### 3. Claim and isolate

Prepare the ordinary item lane:

```text
yoke direct-workflow worktree prepare ITEM --workflow dash --json
```

No environment override is required. Validation-surface provisioning is a
best-effort local lane convenience, not a Dash preparation gate; an HTTPS
control plane has no local capability database to inspect and skips that step
silently. Governed migration rehearsal remains the validation authority when
the instruction changes a database model.

Use the returned absolute `worktree_path` for every read, edit, test, and
git command. Keep the Cursor agent rooted on the main project checkout —
do not call `move_agent_to_root` (or otherwise remount the chat) into
`.worktrees/...`. Yoke worktrees are code lanes, not the conversation home;
remounting assigns a new Cursor conversation id and, after the lane is
removed, leaves Shell stuck on a deleted cwd (`ENOENT`). Pass an explicit
live `working_directory` when Shell would inherit a worktree or deleted
path. The preparation call reuses the item work claim already held
since step 1 (reporting `work-claim:already-owned`, or acquiring it if
absent), validates selected path-claim coverage against the survey,
activates those claims, and creates or reuses the registered worktree.

Activate through the shared lifecycle interpreter:

```text
yoke lifecycle transition ITEM --from idea --to implementing --reason "Dash execution started"
```

The live `conflict_survey` gate requires a recorded, readable touch set and
re-evaluates current contacts, but an overlap does not block the transition.
The `work_claim_activation` gate still verifies that this session owns the
active item claim and that the item has its registered implementation
worktree. Read and resolve every survey advisory through the choices above.

### 4-7. Execute, verify, and close

Read [`verification-and-close.md`](verification-and-close.md) completely,
then follow its implementation, committed-tree verification, merge, evidence,
and terminal close-out sequence.

## Escalate

Halt as soon as the required outcome needs crafted acceptance criteria,
substantial design, durable multi-file coordination, or multiple delivery
slices. Escalation files a new Issue and cancels the Dash, so it is a scope
judgment the operator owns — a deliberate exception to the
kick-off-and-walk-away default. Before drafting the proposed Issue title and
findings, take `PROJECT` from the Dash item detail and read the issue-workflow
projection through registered `workflow.execution_instruction.resolve`:

```text
yoke workflow execution-instruction resolve --workflow issue --project PROJECT
```

Apply every returned instruction, then stop Dash execution at the trigger and
present to the operator:

- the grounded findings and what the instruction turned out to require;
- the remaining outcome that is no longer instruction-sized;
- the proposed Issue title and framing;
- that escalating cancels this Dash.

Then ask whether to escalate, and wait. Do not file the Issue, cancel the
Dash, or continue implementing past the trigger while the answer is pending.

Only after the operator explicitly agrees, run:

```text
yoke direct-workflow dash escalate ITEM \
  --issue-title "<specific title>" \
  --findings "<grounded findings and remaining outcome>"
```

The operation is idempotent: it preserves one link to the absorbing Issue
and cancels the Dash. Stop Dash execution after it succeeds and release the
work claim if the operation did not already do so.

If the operator declines escalation, follow their direction — continue,
narrow, or park the Dash — without filing an Issue.

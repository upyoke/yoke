# Idea — Infer and Create

## 2. Infer metadata from actual context

### a. Project and checkout

Use explicit request, YOKE_PROJECT or registered caller checkout mapping.
Never infer from a conventional slug, ambient config default or sole roster:
```bash
yoke projects list
```
Absent context is project_required: show the roster and ask which project.
Read failure stays visible. Resolve and print that project's registered local
checkout; it is the only root for path investigation. Missing checkout is setup,
not permission to borrow Yoke files. Read [reference-and-scope-verification.md](reference-and-scope-verification.md).

### b. Deployment flow

Follow [infer-deployment-flow.md](infer-deployment-flow.md) before assignment.
It owns defaults, field-based classification, inheritance and missing setup.

### c. Workflow

```bash
yoke workflows definition get --project "$_project" --json
```

Eligible result.workflows rows are active and allow harness_skill entry.
An explicit --workflow must match its exact registry id; reject unknown,
disabled or incompatible rows. Read ordered stages/bindings/policies, never
route by id vocabulary.

Initial Dash binding: read and follow [Dash's procedure](../dash/SKILL.md)
internally so direct filing/execution is atomic. A served worktrees:none,
delivery:merge_free definition supports the complete laneless shortcut
`yoke task TITLE INSTRUCTION --execution-instructions-considered`.
A refine-to-Blitz boundary links exactly one execution strategy document
through strategy.execution.link; intake never copies its plan into body.

Without explicit choice prefer the unique smallest generated_children:none,
single_implementation_lane definition with implement binding. Use the unique
epic_tasks shape only for structural task decomposition/parallel lanes,
not size, duration or file count. Borderline: one binary question with the
actual matched display names. Zero/multiple eligible shapes require operator
selection, never invented workflow ids. No imagined child backlog rows:
the Architect decomposes through persisted epic_tasks in the bound planner.

### c2. Resolve execution instructions before final authoring

Registered `workflow.execution_instruction.resolve`:
```bash
yoke workflow execution-instruction resolve --workflow "$_workflow" --project "$_project" --full
```

Apply its results before final title/body prose. The create-returned instruction
block remains defense in depth, not a substitute for this read.

### d. Priority

Never ask. High: urgent/broken/prod/blocking/hotfix/critical/P0/emergency/outage/down.
Low: nice-to-have/future/someday/eventually/minor/cosmetic/cleanup. Otherwise medium.

### e. Dependencies and Pack reuse

Validate explicit public refs through registered item reads. Record an actual
requested wait with explicit activation and satisfaction: blocker's pinned
status (normally status:done) for item closeout, fact:merged for trunk code,
fact:deployed:ENV for a real live-environment need. Explain detected dependencies.

For a non-Yoke project infer project-owned versus pack-update: would another
project want this when updating that Pack? Reusable capability ships as a new
immutable Pack version in its owner's item and a linked consuming-project item.
Ambiguity gets one binary question. Customized installed files remain project
owned. Print project/workflow/priority/flow-or-omitted/dependencies/Pack stance.

## 3. Cross-project hard block

One item/graph/lane belongs to one deployment project. Independently deliverable
project portions: propose one companion per project and the real dependency,
ask to split; refusal means clarify scope. A producer-led reusable contract/
Pack change automatically gets a consuming-project companion with directional
wait, reciprocal references and exact-candidate consumer verification.
Never give one item a second project's lane.

## 4. Duplicate check before create

Read current project rows for nearby active/refined/planned/blocked scope:
```bash
yoke items list --project "$_project" --fields "id,title,status,workflow_id" --limit 1000
git -C "<absolute-project-checkout>" log --oneline -10
yoke items search "<literal-keywords>" --project "$_project"
```

Inspect likely matching item bodies and relevant commit diffs. Search uses
literal phrase matching, so use2–3 extracted keywords after the broader
current-item/commit scan. A generated BOARD is a view, not current authority.
Classify title/body match, scope overlap or adjacent-distinct work.
Likely duplicates produce an advisory with refs/status/workflow and one
create-anyway yes/no decision; no means use existing item, no matches proceed.

## 5. Create The Item

Invoke items.create bare, without redirection/pipes/inline payload wrapping:
```bash
yoke items create "<title>" "$_workflow" --entry-surface harness_skill --execution-instructions-considered --project "$_project" --priority <priority> --json
```

Include --deployment-flow only for a valid nonempty assignment; never none.
Dry-run adds --dry-run and performs no later writes. Read the original receipt
and failures; do not repeat a mutation to change output. Title/workflow are
positional. An explicit `/yoke idea --workflow blitz` preserves that registry
selection and its refinement/document boundary.

## 5b. Acquire draft claim immediately

**First work action after successful creation**, before artifact survey/writes:
```bash
yoke claims work acquire --item "$ITEM_REF" --reason draft-in-progress
```

Use the returned full ref and claim identity. No claim for dry-run. Hold through
body/AC/budget/readiness; a second worker must not refine an empty spec.
Crashed drafts use the configured session_stale_ttl_minutes safety window;
frontier idea-incomplete still guards title-only drafts after that window.
After claiming, follow [delivery-requirements.md](delivery-requirements.md)
when the operator requested deployed evidence/approval.

## 6. Persist real dependencies

```bash
yoke items dependency add <new-public-ref> <blocker-public-ref> operator --gate-point activation --satisfaction status:done --rationale "<verified-requested-wait>"
```
Choose the actual pinned satisfaction described above. Dry-run prints only.
For physical-path overlap, classify through path-claim-blocking before any
edge; independent coordination_only is not an activation wait.

## 7. Confirmation after full closure

Only after body, readiness and claim release, show created ref, actual issue
link/number and persisted dependencies. Resolve next_skill_id from fresh item
detail and [shared handoff](../shared/stage-handoff.md), never memorized progression.
For Blitz explain refinement must link exactly one execution strategy document;
do not start execution or create children before it. Laneless floor dispatch
also follows its actual binding, never inferred literal stage names.

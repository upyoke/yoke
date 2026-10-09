# Shepherd — Architect and plan simulation

Planning artifacts live in control plane; no plan worktree or code writes.

## Produce and persist

Early planning stamp uses lifecycle.transition.execute only when target is
inside the binding, never through-stage. Resume at that target skips the write;
fresh status verifies it. A single-edge stays at source until all reviews pass.

Run readiness.prd_validate before Architect. FAIL: persist BLOCKED with actual
failures/recovery, no dispatch. PASS warnings enter prompt. Descriptor role
architect, reflection schema, filled with original ref/title/workflow/root,
current caveats, attempt/Boss feedback and Simulator gaps on retry.

Architect reads spec/design from DB, body only when a structured field is empty;
no inline body. Require live code references, Simplify reuse (or explicit no
relevant existing surface), smallest complete scope/declared exclusions,
extension-versus-new justification and future-concept coordination lens.
Deferrals persist Description/Reason/UNFILED work-item table.
Return Technical Plan, task content and Worktree Plan; no files.

Capture **full** output immediately. Missing ## Technical Plan/empty/truncated:
NOT_READY, retry within MAX_ATTEMPTS; limit persists BLOCKED and stops.
Extract complete sections structurally, not multiline awk slicing.
Typed field writes technical_plan then worktree_plan **before tasks**,
source shepherd/original target; any failed write is NOT_READY/no advance.

Read technical_plan back nonempty; up to two retries with readback, then stop
NOT_READY before through-stage. For each task use workflow_item.epic_task.add:
title/body/worktree/context_estimate/dependencies; body stays end-to-end.
File entries now use registered workflow_item.epic_task.file_add:

```bash
yoke workflow-item epic-task file-add --epic ITEM --task-num {task_num} --file-path PATH --action ACTION
```

Only after all tasks/files persist, required_per_task claims use each eligible
task's exact persisted files (exclude stopped/failed), never branches/prose/
one parent claim attached everywhere. Nonempty budget:

```bash
yoke claims path register --item ITEM --task-num {task_num} --paths PATHS --allow-planned
```

Empty budget requires explicit task exception:

```bash
yoke claims path register --item ITEM --task-num {task_num} --mode exception --exception-reason "Architect persisted no repository file budget for this task"
yoke claims path required-gate ITEM --json
```

Any gate verdict other than pass is NOT_READY and blocks handoff.

## Simulate before Boss

Dispatch simulator descriptor, phase plan, actual root/internal ID plus original
public ref. It reads all task bodies and spec/technical_plan/worktree_plan via
registered readers; body only if empty. Trace execution across every task.

CLEAN: persist full report, then Boss. GAPS FOUND: Architect fix with report,
then resimulate, at most MAX_SIMULATOR_FIX_CYCLES fixes. Exhausted gaps:
persist failing report/QA, HALT at live stage, **no plan-phase PROCEED bridge**:

```bash
yoke workflow-item epic-task simulation-upsert --epic ITEM --phase plan --stdin
```

Use complete report through stdin, inspect receipt. Pinned simulation gate needs
fresh passing evidence or explicit authorized waiver. Offer: patch/replan then
resimulate; authorized waiver of exact requirement with rationale; rescope or
stop through the actual pinned lifecycle. Discover requirement with registered
qa.requirement.list, not constructed IDs/SQL aliases:

```bash
yoke qa requirement list --item ITEM --json
```

Select plan simulation requirement, read waive --help and act only with its
required authority. No guessed slash stop or automatic waiver.

Boss scope plan reads persisted artifacts. READY/CAVEATS follows declared
status handler; no merge. NOT_READY revises plan: list tasks and remove only
planning/planned rows through workflow_item.epic_task.remove with reason,
then retry Architect/validation with feedback. Existing implementation states
must be inspected, never deleted by this planning retry.
Next: [boss-verdict.md](boss-verdict.md).

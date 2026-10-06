# /yoke advance step 4 — phase dispatch and query ordering

## 4. Phase Dispatch

Implementation entry never reaches this step: the `implement` stage skill
enters through the engine and calls this sub-skill only for later status
writes. Every target that does reach it (`reviewing-implementation`,
`reviewed-implementation`, `polishing-implementation`, `implemented`,
`release`, `done`, or any planning-phase target) needs no gate recipe: the
transition in [`finalize.md`](finalize.md) evaluates every listed and
structural gate itself and refuses with a named reason and recovery.

**Gates:** Read `.agents/skills/yoke/advance/preflight.md`
- The inventory of every gate the transition enforces — dependency edges,
  File Budget coverage, shepherd verdict, generated-task
  existence and completion, deferred items, merge record, done ceremony, and
  QA — with when each holds, its refusal code, and its recovery.

**Browser QA:** Read `.agents/skills/yoke/advance/browser-qa.md`
- Applies when the target transition has attached Browser-method cases; run
  them before the QA-gated transition, which refuses while they are unrun.

**Deployed-stack QA:** Read `.agents/skills/yoke/advance/project-e2e.md`
- Applies to: workflow transition = `release`
- Executes every attached `Command` case whose project-owned configuration declares the `e2e` scope, with `BASE_URL` supplied from the ephemeral environment
- Self-skips when no deployed-stack plan is attached; skip for all other transitions

**Finalize:** Read `.agents/skills/yoke/advance/finalize.md`
- Applies to: every transition that reaches this point
- Handles: status update, GitHub sync, commit, report, and next-step guidance

## Query ordering and parallel-safe groups

Respect the ordering constraints below. Only reads explicitly described as
independent may run in parallel.

**Step 1 — Pinned workflow lookup:**
- Call `workflows.item.get` first. Its `workflow_id` and logical
  `workflow_version` select the exact `workflows.version.get` read used for
  auto-advance navigation; never substitute the current workflow definition.
- After `workflows.item.get` returns, the pinned `workflows.version.get` read
  and `items get {N} title` are independent and may run in parallel.

**Gates:**
- The transition evaluates every gate on its own write; there are no gate reads to order. Acceptance criteria use PRD-9 at Refine closure through `readiness.check.run`; they are not an implementation-entry gate.

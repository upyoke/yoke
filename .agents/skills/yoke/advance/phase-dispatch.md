# /yoke advance step 4 — phase dispatch and query ordering

## 4. Phase Dispatch

**Implementation entry (`_target = "implementing"`) is orchestrator-driven.** When `_target` resolves to `implementing` (the `/yoke advance PREFIX-N implementation` path), invoke the canonical orchestrator instead of reading and executing each phase doc inline:

Before invocation, require `_target_skill=advance` and a
single-session worktree policy — `single_implementation_lane`, or `none`
for a laneless workflow, where the orchestrator skips worktree creation
and the item runs in place. Route `conduct` to `/yoke conduct PREFIX-N`
and halt on every other mismatch; this engine is an skill-specific
contract, not a generic transition shortcut.

```bash
yoke advance implementation-entry --item PREFIX-N
```

That command is how this skill enters the engine; the operator surface stays
`/yoke advance PREFIX-N implementation`. Run
`yoke advance implementation-entry --help` for the flag matrix: `--no-worktree` for evidence-only items, `--force` for the operator-asserted override path, `--qa-bypass` to bypass implementation QA when truly needed. The orchestrator composes preflight gates → `worktree_preflight.run_preflight` (bundles claim + activation + worktree creation/reuse) → environment (capability-gated) → finalize (`lifecycle.transition.execute`) inside one Python process and emits one `AdvancePhaseCompleted` event per phase. It is idempotent: rerunning against an item already at `implementing` reuses the worktree, re-acquires the same claim, and skips the status flip rather than re-emitting it. On preflight failure the orchestrator stops before activation/worktree/finalize and prints the gate narrative; on `worktree-create-failed` it releases the claim with reason `worktree-create-failed`; on finalize failure the worktree and claim remain in place so the next invocation can converge. Verify the phase trail with `yoke events query --item PREFIX-N --event-name AdvancePhaseCompleted`.

Before worktree preflight or any claim/lane mutation, the orchestrator corroborates the acting session through the same canonical ambient resolver used by the PreToolUse write guards. Missing identity refuses as `write-guard-identity-unresolved`; an explicit `--session-id` must match the ambient result. Repair the harness env stamp, process-anchor registry, or Cursor conversation map and retry — never provision an unwritable lane with a guessed identity.

After the orchestrator returns success, the same harness session continues into worktree-bound implementation work via the implementing sub-skill handoff documented in [`finalize.md`](finalize.md) (`## Implementation-entry Sub-skill Handoff`).

The phase reference docs ([`preflight.md`](preflight.md), [`activation.md`](activation.md), [`worktree.md`](worktree.md), [`environment.md`](environment.md), [`finalize.md`](finalize.md)) remain in the tree as reference material the orchestrator consumes through its Python code — they document the contract each composed helper honors, not a per-call agent-driven sequencing recipe.

**Non-implementing targets** (manual advance to `reviewing-implementation`, `reviewed-implementation`, `polishing-implementation`, `implemented`, `release`, `done`, or any planning-phase target) still run through the legacy phase docs below. The orchestrator only covers implementation entry today; the post-implementation phases retain their existing doc-driven flow.

**Preflight Gates:** Read `.agents/skills/yoke/advance/preflight.md`
- Applies to: all non-implementing transitions (hard-block dependency, AC,
  coverage, pinned-skill handoff, generated-task, merge-verification, and
  done-redirect gates).
- Generated-task gates run only when
  `policies.generated_children=epic_tasks`; skill-specific gates run only
  when the target path crosses that pinned binding. Merge and done gates remain
  target-stage-specific.

**Browser QA:** Read `.agents/skills/yoke/advance/browser-qa.md`
- Applies to: target = `reviewed-implementation`, `implemented`, or `polishing-implementation`
- Skip for all other targets

**Deployed-stack QA:** Read `.agents/skills/yoke/advance/project-e2e.md`
- Applies to: workflow transition = `release`
- Materializes attached QA plans and executes every `Command` case whose project-owned configuration declares the migrated `e2e` scope, with `BASE_URL` supplied from the ephemeral environment
- Self-skips when no deployed-stack plan is attached; skip for all other transitions

**Finalize:** Read `.agents/skills/yoke/advance/finalize.md`
- Applies to: all non-implementing transitions that reach this point
- Handles: status update, GitHub sync, commit, report, implementation-complete next-step guidance, implementing sub-skill handoff (implementing-target callers reach the sub-skill handoff via the orchestrator's success exit; this doc still documents the handoff contract for both paths)

## Query ordering and parallel-safe groups

Respect the ordering constraints below. Only reads explicitly described as
independent may run in parallel.

**Step 1 — Pinned workflow lookup:**
- Call `workflows.item.get` first. Its `workflow_id` and logical
  `workflow_version` select the exact `workflows.version.get` read used for
  auto-advance navigation; never substitute the current workflow definition.
- After `workflows.item.get` returns, the pinned `workflows.version.get` read
  and `items get {N} title` are independent and may run in parallel.

**Preflight — Reconciliation gate:**
- `items get {N} deployment_flow`, `items get {N} project`, `items get {N} github_issue` — all independent reads

**Preflight — Dependency + AC gates:**
- `evaluate-gate "PREFIX-N" "activation"` and `check_ac_presence "PREFIX-N"` — independent gate evaluations

**Environment — Ephemeral setup:**
- `yoke ephemeral-env update "$_env_id" url "$_ephemeral_url"` and `yoke ephemeral-env update "$_env_id" deployed_sha "$_deployed_sha"` — independent writes to the same env record (different fields)

**Implementation — Edit batching:**
- When multiple Edit calls target different files, run them in parallel. Use `replace_all: true` when the old string is unique enough for a safe global replace.

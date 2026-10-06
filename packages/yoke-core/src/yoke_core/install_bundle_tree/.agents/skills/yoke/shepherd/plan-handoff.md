# Shepherd: Architect Invocation and Plan Handoff

Covers the the plan-production edge Architect phase and the the final review edge transition: status transition, PRD gate, Architect invocation, DB writes, Simulator loop, and Boss handoff.

**Inherited from router:** `MAX_ATTEMPTS`, `MAX_SIMULATOR_FIX_CYCLES`, `_num`, `_workflow_id`, `_title`, `_item_status`, `_scholar_context`, `_prior_caveats`, `_transition`, `_attempt`, `_session_id`, `_worker_name`.

**After this step completes:** Continue with Boss review in `boss-verdict.md`.

---

## 5d. Invoke Worker ({_plan_transition} -- Architect)

This transition writes plan data directly to the DB on main. No plan worktree is created.

### 0. Show active planning inside the binding

When `_target_stage` is inside the binding (not its handoff), dispatch
`lifecycle.transition.execute` with the resolved bare `item_id` and
`payload = {target_status: _target_stage, source_status: _source_stage}`.
If resuming at that target, do not repeat the write. Re-read the status after
success. A one-edge segment stays at its source until all reviews pass, so
it cannot hand off before artifacts and verdicts exist.

### 1. Derive epic ID
```bash
_epic_id=$_num # resolved bare item ID from entry
```

### 2. PRD quality gate (pre-Architect validation)
Before invoking the Architect, run the registered read-only PRD validator:
```bash
yoke readiness prd-validate "$_item_ref"
```
If exit code is 1 (FAIL), do not invoke the Architect. Persist a BLOCKED verdict with the validation failures, present the named recovery, and stop.
If exit code is 0 with warnings, proceed but include the warnings in the Architect prompt context.

### 3. Invoke Architect
The Architect reads the item spec and plan from the DB (structured fields first, body fallback if empty). Do NOT pass inline body content.

**Dispatch:** descriptor `DispatchDescriptor(role="architect")` rendered via `yoke_core.domain.dispatch_descriptors.render_for_harness(descriptor, harness_id)`. Result-schema markers: `---REFLECTION-START---`. The descriptor's `prompt: |` block is filled with:
```
 Decompose PREFIX-{N} into tasks.
 Title: {_title}
 Workflow: {_workflow_id}
 Repository root: {MAIN_ROOT}

 Read the item spec and design from the DB before planning (structured fields first, body fallback):
 yoke items get PREFIX-{N} spec
 If empty, fall back to: yoke items get PREFIX-{N} body
 Also read design spec if present: yoke items get PREFIX-{N} design_spec

 {_prior_caveats_block if any}

 Attempt {_attempt} of {MAX_ATTEMPTS}.
 {if _attempt > 1: "Previous Boss feedback:\n{_boss_feedback}\n\nSimulator gap report:\n{_sim_report}"}

 Apply the simplify three-axis vocabulary at plan-author time. See AGENTS.md "## Simplify — three-axis doctrine": name the existing surfaces the plan will reuse (or explicitly justify "no relevant existing surface"), cap scope with out-of-scope boundaries, justify new infrastructure against what already exists, and apply the future-concept lens when the plan touches actors, sessions, heartbeats, ownership, leases, claims, approvals, overrides, evidence, run records, journals, packets, locks, or shared-state coordination.

 If you defer any work from scope during planning (e.g., "deferred to a follow-up",
 "out of scope for this epic"), update the ## Deferred Items section in the item body
 with a table entry for each deferral: | Description | Reason | Work item (UNFILED) |.
 If no ## Deferred Items section exists yet, create one.

 Return: Technical Plan section, task content, Worktree Plan section.
 Do not write any files.
```

**Architect output capture guarantee.** Immediately after the Agent tool returns, capture the Architect's full output into `_architect_output`. Verify it contains `## Technical Plan`:
- If the output is empty or does not contain `## Technical Plan`, treat this as NOT_READY. Log: `"Architect returned empty/truncated output (no ## Technical Plan heading). Treating as NOT_READY."` If `_attempt < MAX_ATTEMPTS`, retry the Architect invocation. Otherwise, write a BLOCKED verdict and stop.
- If the output contains `## Technical Plan`, proceed to step 4.

### 4. Write Architect output to DB

**Field write before task upserts (defense-in-depth).** Write the plan text to structured fields BEFORE upserting tasks to `epic_tasks`. This ensures that if the process fails partway through, the more visible artifact (rendered body) is written first.

Extract `## Technical Plan` and `## Worktree Plan` sections from
`_architect_output` and write them to structured fields via the
`items.structured_field.replace` function call (envelope in
[`../idea/body-and-sync-functions.md`](../idea/body-and-sync-functions.md)).
**Never use awk** to slice plan sections — it chokes on newlines in
multiline DB content. Extract the sections into shell variables (e.g.,
via `python3` slicing) before dispatching.

Two dispatches, in order:

1. `items.structured_field.replace` with `target = {kind: "item",
   item_id: $_num}`, `payload = {field: "technical_plan", content:
   "$_tech_plan_content", source: "shepherd"}`. If `success=false`,
   log `ERROR: structured field write failed for technical_plan on
   $_item_ref. STOP -- do not advance status.` and treat as NOT_READY.
2. `items.structured_field.replace` with the same `target` and
   `payload = {field: "worktree_plan", content: "$_wt_plan_content",
   source: "shepherd"}`. Same error handling.

**Post-write field verification.** After the structured-field
writes, re-read `technical_plan` via the `items.get.run` function
call (`payload = {fields: ["technical_plan"]}`) and confirm
`result.fields.technical_plan` is non-empty. If empty:

- Log
  `"VERIFICATION FAILED: technical_plan field is empty for $_item_ref
  after write. Retrying field write (attempt {retry}/2)."`
- Retry the `items.structured_field.replace` dispatch up to 2 times.
- If all retries fail, do not advance to `_shepherd_through_stage`. Log the failure
  and treat as NOT_READY.
- If verification passes, log
  `"VERIFIED: technical_plan field populated for $_item_ref after
  write."`

Then, for each task produced by the Architect, dispatch the
`workflow_item.epic_task.add` function call (envelope in
[`../idea/body-and-sync-functions.md`](../idea/body-and-sync-functions.md)):
`target = {kind: "epic_task", epic_id: $_epic_id, task_num:
<N>}`, `payload = {title, body, worktree, context_estimate,
dependencies}`. The body payload carries the generated task body
end-to-end — no separate body write is required. For file entries,
the `db_router epic file-add` operator-debug shell write surface
remains the current path (the `workflow_item.epic_task_file.*`
family is not yet exposed).

When `_path_claim_policy` is `required_per_task`, materialize task scope
only after every task and file entry above is persisted. For each eligible
task (exclude `stopped` and `failed`), read its exact `epic_task_files`
rows. A non-empty budget registers concrete task scope:

```bash
yoke claims path register --item "$_item_ref" --task-num "<N>" \
  --paths "<comma-separated persisted file_path values>" --allow-planned
```

An empty budget must use an explicit task-bound exception instead:

```bash
yoke claims path register --item "$_item_ref" --task-num "<N>" \
  --mode exception --exception-reason \
  "Architect persisted no repository file budget for this task"
```

Never infer task ownership from task prose or branches and never bind the
parent claim to every task. After all registrations, run
`yoke claims path required-gate "$_item_ref" --json`; any verdict other than
`pass` is NOT_READY and blocks the handoff to `_shepherd_through_stage`.

### 5. Run Simulator loop (max `MAX_SIMULATOR_FIX_CYCLES` fix cycles)

**Dispatch:** descriptor `DispatchDescriptor(role="simulator")` rendered via `yoke_core.domain.dispatch_descriptors.render_for_harness(descriptor, harness_id)`. Result-schema markers: `SIMULATION: CLEAN|GAPS FOUND`, `---REFLECTION-START---`. The descriptor's `prompt: |` block is filled with:
```
 Simulate the plan for epic {_epic_id} (PREFIX-{N}).
 Phase: plan
 Repository root: {MAIN_ROOT}
 Read task content from the DB via yoke workflow-item epic-task body-get.
 Read the structured item artifacts via the registered `yoke items get` and `yoke epic-tasks list` readers:
 - spec: items get PREFIX-{N} spec
 - technical plan: items get PREFIX-{N} technical_plan
 - worktree plan: items get PREFIX-{N} worktree_plan
 If any structured field is empty, fall back to: items get PREFIX-{N} body

 Trace execution paths across all tasks. Report gaps.
```

Parse the Simulator's result for `## Result: CLEAN` or `## Result: GAPS FOUND`.

- If **CLEAN**: persist the simulation report (step 6), then proceed to Boss review.
- If **GAPS FOUND** and fix cycles remain: re-invoke Architect in fix mode with the gap report, then re-run Simulator.
- If **GAPS FOUND** and no fix cycles remain: **HALT at the live stage.** Plan-phase gaps must be resolved before the plan can advance — there is no PROCEED-with-gaps bridge at this phase (unlike integration). Persist the simulation report (step 6 still runs so the failing QA run is recorded), then STOP — do not proceed to Boss. The pinned definition's plan-simulation gate refuses its declared transition until fresh passing evidence exists or an explicit waiver is recorded. Surface the blocker to the operator with three exits:
  1. **Patch and re-simulate** — fix the gaps in the plan/task bodies (or re-run Architect manually), then re-run shepherd. `simulation-upsert` overwrites prior runs, so a clean re-simulation replaces the failing row.
  2. **Waive the requirement** with explicit operator rationale. Find the requirement id, then waive:
     ```bash
     _req_id=$(yoke db read --format lines "SELECT id FROM qa_requirements WHERE item_id=$_epic_id AND qa_kind='simulation' AND success_policy LIKE '%\"phase\":\"plan\"%'")
     yoke qa requirement waive --requirement-id "$_req_id" --rationale "<rationale>" --source operator --force
     ```
  3. **Re-scope or stop** — narrow the epic and re-shepherd, or `/yoke stop PREFIX-{N}`.

### 6. Write simulation report to DB
```bash
echo "{simulation_report}" | yoke workflow-item epic-task simulation-upsert --epic "$_epic_id" --phase plan --stdin
```

### 7. Boss review
Boss review happens in step 5e (see `boss-verdict.md`) with `scope=plan`.

### 8. On Boss READY/CAVEATS
No merge is needed; planning artifacts are in the control plane. Follow the verdict handler to verify the declared target or advance it after review.

### 8. On Boss NOT_READY
List task data, remove each planning/planned task through the registered task owner, and re-attempt from step 2 (re-invoke Architect with feedback):
```bash
yoke epic-tasks list --epic "$_epic_id"
yoke workflow-item epic-task remove --epic "$_epic_id" --task-num "{each task_num}" --reason "Boss requested plan revision"
```

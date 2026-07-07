---
name: plan
description: Invoke the Architect subagent to produce a technical plan. Epics get task decomposition; issues get a lightweight `technical_plan` field.
argument-hint: "{epic-id}"
---

# Internal sub-skill -- called by shepherd and conduct. Not operator-facing.

# /yoke plan {epic-id}

Translate an item spec into a technical implementation plan.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `{epic-id}` — Planning target. Accepts:
 - `YOK-N` item ID
 - epic ID (numeric item ID)
 - title slug (lowercase title with spaces replaced by `-`)

## Philosophy

**Be the giant.** We stand on inherited shoulders; leave a leg up for the next agent by making this artifact cold-start complete. Plan is the Architect handoff surface, so the prompt must point at the authoritative spec, relevant context, and the exact planning mode without making the Architect rediscover basics.

**Verify before decomposition.** Planning should start from validated, current specs and not from memory or stale body text. A bad planning input multiplies downstream cost across every task.

## Steps

Stamp the session mode so the board's active-session row reflects the live phase (default `wait` misrepresents an active plan). Use the registered session wrapper:

```bash
yoke sessions touch \
 --mode plan
```

1. **Resolve the backlog item:**
 Resolve by `id` first (if `{epic-id}` is `YOK-N`, strip the prefix to get the numeric `id` — for epic items, that numeric `id` IS the same value referenced as `epic_id` in `epic_tasks`), otherwise by title slug:
 ```bash
 python3 -m yoke_core.cli.db_router query "SELECT id, title, type, status FROM items WHERE id={N-from-YOK-if-provided} OR lower(replace(title,' ','-'))=lower('{epic-id}') ORDER BY CASE WHEN id={N-from-YOK-if-provided} THEN 0 ELSE 1 END LIMIT 1;"
 ```
 If you also need the rendered body, fetch it separately (it is a virtual rendered field, not an `items` column):
 ```bash
 yoke items get YOK-{N} body
 ```
 If no item found, stop: "No backlog item found for `{epic-id}`. Create one with `/yoke idea` first."
 Verify the item is in a planning-eligible lifecycle state:
 - `type=epic`: `refined-idea`, `planning`, or `plan-drafted`
 - `type=issue`: `refined-idea`
 If the item is still `idea` or `refining-idea`, suggest `/yoke refine YOK-{N}` first. If an epic has not yet entered planning, suggest `/yoke shepherd YOK-{N}` first.

 Determine plan mode from `type`:
 - `type=epic` → **epic plan mode** (full task decomposition)
 - `type=issue` → **issue plan mode** (lightweight `technical_plan` field only)

 ```bash
 _epic_id={resolved numeric item ID from step 1}
 # Use _epic_id (numeric item ID) for ALL python3 -m yoke_core.cli.db_router epic calls below.
 ```

2. **PRD quality gate (pre-planning validation):**
 Run the registered PRD validator to ensure the item body meets minimum quality standards before the Architect runs. This applies to both epic and issue mode.

 ```bash
 yoke readiness prd-validate "YOK-{N}"
 ```

 **If exit code is 1 (FAIL-level issues):** stop and present the validation report to the user. Do NOT proceed to the Architect. The report includes specific fix guidance for each failing check.

 > PRD quality gate failed. Fix the issues above before planning.
 > After fixing, re-run `/yoke plan {epic-id}`.

 **If exit code is 0 but warnings exist:** present the warnings to the user and ask for confirmation to proceed. Warn that unresolved items (e.g., Open Questions) may lead to planning gaps.

 **Checks performed by the internal PRD validator:**
 - **PRD-1:** Problem/Why section exists and is substantive
 - **PRD-2:** Functional requirements section has at least one testable requirement
 - **PRD-3:** Success Metrics section exists with measurable criteria
 - **PRD-4:** Open Questions trigger WARN if unresolved items remain
 - **PRD-5:** Goals section exists with concrete, measurable outcomes

3. **Check for existing plan data (epic mode only):**
 If plan mode is `issue`, skip this step (issues do not use `epic_tasks`).

 If plan mode is `epic`, check whether `epic_tasks` rows already exist for this epic in the DB:
 ```bash
 _existing_tasks=$(python3 -m yoke_core.cli.db_router query "SELECT COUNT(*) FROM epic_tasks WHERE epic_id={epic-id}'")
 ```

 **If `_existing_tasks` > 0 AND any tasks have status other than `planning` or `planned`:** stop with:
 > This epic already has tasks in progress. Re-planning is not supported.

 **If `_existing_tasks` > 0 AND all tasks are `planning` or `planned`** (prior interrupted run): ask user: **Resume** or **Restart**?
 - **Resume:** Skip to step 11 (review gate) to re-present the plan from the existing DB data.
 - **Restart:** Delete existing task data and start fresh:
 ```bash
 python3 -m yoke_core.cli.db_router query "DELETE FROM epic_task_files WHERE epic_id={epic-id}'"
 python3 -m yoke_core.cli.db_router query "DELETE FROM epic_tasks WHERE epic_id={epic-id}'"
 ```
 Then continue normally to step 4.

 **If `_existing_tasks` is 0:** continue normally.

4. **Scan the codebase** using the Explore subagent (fast, read-only, Haiku):
 - Current architecture and patterns
 - Existing modules that might be affected
 - Testing patterns and frameworks
 - Documentation structure in `/docs`

 **DB column reference for subagent prompt:** When the Explore subagent may query the DB, include this in the prompt:
 > DB column cheat sheet — use these exact names in SQL:
 > - `events`: `event_name`, `event_type`, `source_type`, `created_at`, `envelope` (NOT `type`/`timestamp`/`source`/`detail`/`context`/`worker`/`payload`/`outcome`)
 > - `deployment_runs`: `id`, `current_stage`, `created_by` (NOT `run_id`/`deploy_stage`/`creator`/`item_id`)
 > - `deployment_run_items`: composite PK `run_id` + `item_id` (NO `id` column; zero rows are valid for started environment-level runs)
 > - `qa_runs`: `req_id`, `verdict` (NOT `requirement_id`)
 > - `epic_tasks`: `epic_id`, `task_num`, `dependencies` (NOT `item_id`/`task_number`/`depends_on`)
 > - `ouroboros_entries`: `body`, `created_at` (NOT `entry`/`timestamp`)
 > - `shepherd_verdicts`: `item` (NOT `item_id`), `transition` (NOT `gate`)
 > - `project_capabilities`: `type` (NOT `capability`/`name`/`capability_type`), `config`, `settings`
 > - `projects`: `id` (NOT `project_id`/`name`), `repo_path` (NOT `path`/`repo`), `github_repo` (NOT `repo_url`/`github_url`)

5. **Read inputs:**
 - The design spec from the DB (if it exists):
 ```bash
 _has_design=$(python3 -m yoke_core.cli.db_router designs exists {N})
 if [ "$_has_design" = "true" ]; then
 _design_body=$(python3 -m yoke_core.cli.db_router designs get-body {N})
 # Returns raw body text to stdout — safe for bodies containing pipes
 fi
 ```
 - Contents of `/docs/` for project context

6. **Invoke the `yoke-architect` subagent** with:
 - The item ID (e.g., `YOK-N`) — the Architect reads the authoritative spec from the DB itself via `yoke items get YOK-{N} spec`. Do NOT pass inline spec content.
 - The design spec (if any)
 - Codebase context from step 4
 - `/docs` content

 **Mode-specific output contract:**
 - **Issue mode:** Architect returns a lightweight `## Technical Plan` section only (approach, key decisions, edge cases, testing strategy). No task decomposition. No worktree plan.
 - **Epic mode:** Architect returns `## Technical Plan`, task content (for `epic_tasks.body`), and `## Worktree Plan`.

7. **Ouroboros reflection capture:**
 Search the Architect subagent's response for text between `---REFLECTION-START---` and `---REFLECTION-END---` delimiters. If found, extract all `---BEGIN ENTRY---` / `---END ENTRY---` blocks from within and persist each entry via:
 ```bash
 yoke ouroboros entry insert --agent "architect" --context "plan {epic-id}" --category "{category}" --observation "{observation}"
 ```
 If no reflection delimiters are found, silently continue.

8. **Write the Architect's task data to the DB (epic mode only):**
 If plan mode is `issue`, skip this step entirely. Do NOT write `epic_tasks` or `epic_task_files`.

 If plan mode is `epic`, for each task produced by the Architect:

 a. **Add the task row.** Dispatch the
    `workflow_item.epic_task.add` function call (envelope in
    [`../idea/body-and-sync-functions.md`](../idea/body-and-sync-functions.md)):
    `target = {kind: "epic_task", epic_id: <id>, task_num: <N>}`,
    `payload = {title, body, worktree: "YOK-{N}", context_estimate,
    dependencies}`. The worktree assignment MUST use the canonical
    `YOK-{N}` format (where N is the backlog item ID), regardless of
    what the architect proposed; the handler accepts the value
    verbatim.

 b. **(body is written by the add call above)** — the
    `workflow_item.epic_task.add` payload's `body` field carries the
    generated task body content end-to-end. If you need to rewrite a
    task body after the row exists (re-plan within the same skill
    invocation), dispatch `workflow_item.epic_task.body_replace` with
    `target = {kind: "epic_task", epic_id, task_num}` and `payload =
    {body: "<full new task body>"}`.

 c. **Add file entries** for each file in the task's Files Touched
    section via the operator-debug shell read/write surface
    `python3 -m yoke_core.cli.db_router epic file-add "{epic-id}"
    "{task_num}" "{file_path}" "{action}"` (where `{action}` is
    `create`, `modify`, or `delete`). The
    `workflow_item.epic_task_file.*` family is not yet exposed; this
    CLI write stays on the epic-internal shell surface until the
    function family lands.

9. **Write plan content to structured fields:**

 - **Issue mode:**
   - Dispatch `items.structured_field.replace` with `target = {kind:
     "item", item_id: <id>}` and `payload = {field: "technical_plan",
     content: "<generated plan>", source: "plan"}`. Replacing the
     existing `technical_plan` field is fine; do not append duplicate
     plan sections into rendered body text.
   - Do NOT create `worktree_plan`.
   - Do NOT create `epic_tasks` rows.

 - **Epic mode:**
   - Dispatch `items.structured_field.replace` for both
     `technical_plan` and `worktree_plan` (one call each).
   - Keep task decomposition in DB tables (`epic_tasks`,
     `epic_task_files`); those landed via the
     `workflow_item.epic_task.add` calls in step 8.

 Note: No filesystem artifacts are created. All plan data is stored in DB-backed fields and tables.

10. **Update backlog item status (epic mode only):**
 Dispatch the `lifecycle.transition.execute` function call (`target =
 {kind: "item", item_id: <N>}`, `payload = {target_status: "planned",
 source_status: "<current>"}`) to advance the linked epic item to
 `planned`. In issue mode, do not move the item to `planned`; issues
 enter implementation from `refined-idea`.

11. **Present the plan to the user for review:**
 Present mode-appropriate output:

 - **Issue mode:** Show the generated `technical_plan` content and ask for confirmation.
 - **Epic mode:** Show task table, worktree plan, and any L-sized tasks for scrutiny:
 ```bash
 yoke epic-tasks list --epic "{epic-id}"
 ```

 For deep review of specific tasks:
 ```bash
 yoke workflow-item epic-task body-get --epic "{epic-id}" --task-num "{task_num}"
 ```

 Ask for explicit user confirmation.

 **If the user rejects the plan:**
 - Issue mode: do not update status; stop.
 - Epic mode: delete task data from DB and stop:
 ```bash
 python3 -m yoke_core.cli.db_router query "DELETE FROM epic_task_files WHERE epic_id={epic-id}'"
 python3 -m yoke_core.cli.db_router query "DELETE FROM epic_tasks WHERE epic_id={epic-id}'"
 ```
 Do NOT update backlog status. Stop here.

11b. **Post-confirmation bookkeeping (on main):**
 On user confirmation (epic mode only): dispatch the
 `lifecycle.transition.execute` function call to advance the linked
 epic item to `planned`, then commit the cached changes with
 `git diff --cached --quiet || git commit -m "YOK-{N}: defined →
 planned"`. In issue mode, do not write any `epic_tasks` data and do
 not change lifecycle status. `epic_tasks.epic_id` is the sole live
 parent-epic relation (bare integer; matches `{N}` when the item is
 itself the epic).

12. **Recommend simulation:**
 - **Epic mode:** recommend `/yoke simulate {epic-id}` before `/yoke conduct YOK-{N}`.
 - **Issue mode:** simulation is not required (no task graph). Continue directly to `/yoke advance YOK-{N} implementation`. The Engineer reads `technical_plan` from the structured field / rendered item body.

## Review Checklist for the User

Remind the user to check:
- [ ] Technical approach clarity — can implementation proceed without guessing?
- [ ] Edge-case coverage — are risky failure paths addressed?
- [ ] Test strategy quality — are verification steps concrete and sufficient?
- [ ] (Epic mode only) Task sizes — are any suspiciously large?
- [ ] (Epic mode only) Interface contracts and dependencies — do provides/expects match?
- [ ] (Epic mode only) Cross-script contracts — do tasks that call existing scripts document data schemas, subprocess env propagation, and error model changes?
- [ ] (Epic mode only) File overlap/worktree assignments — does parallelization look safe?

## Notes

- The Architect subagent cannot write files — it produces content that this command writes to the DB.
- Issue-mode planning is intentionally lightweight: `technical_plan` only, no task decomposition tables, and no `planned` status.
- Epic-mode planning remains full decomposition via `epic_tasks` + `epic_task_files`.
- This is the most important review gate. Plan quality strongly determines execution quality.
- The user can edit epic task content via the
  `workflow_item.epic_task.body_replace` function call after this
  command if they want to adjust scope, acceptance criteria, or
  interface contracts.
- All plan data is written directly to DB-backed state on main. No plan worktrees are created.
- If planning is interrupted (crash, context limit, user abort), existing epic task data can be resumed or restarted on the next `/yoke plan {epic-id}` invocation.

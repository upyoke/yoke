# Simulate Phase: Epic Simulation Flow

This phase owns per-epic simulation before any optional auto-fix loop.

## 1. Verify The Epic Exists

Check that `epic_tasks` rows exist for this epic in the DB:

```bash
_task_count=$(python3 -m yoke_core.cli.db_router query "SELECT COUNT(*) FROM epic_tasks WHERE epic_id='{epic-id}'")
```

If `_task_count` is `0`, tell the operator to run `/yoke plan {epic-id}` first.

## 2. Auto-Detect Simulation Phase

Query task statuses from DB:

```bash
yoke epic-tasks list --epic "{epic-id}"
```

Each row returns `task_num|title|status|worktree|...`.

- If all tasks have status `planning` or `planned` -> **Plan simulation**
- If all tasks have status `completed` or `merged` -> **Integration simulation**
- If `--force-integration` is present -> **Integration simulation** regardless of task state
- Otherwise -> report current task states and stop with guidance to wait or use `--force-integration`

## 3. Gather Context For The Simulator

Resolve the backlog item ID:

```bash
_item_id=$(python3 -m yoke_core.cli.db_router query "SELECT id FROM items WHERE id={epic-id} AND type='epic'")
```

### Plan simulation context

- Read structured fields:
 ```bash
 yoke items get $_item_id spec
 yoke items get $_item_id technical_plan
 yoke items get $_item_id worktree_plan
 ```
- Read all task content:
 ```bash
 yoke workflow-item epic-task body-get --epic "{epic-id}" --task-num "{task_num}"
 ```

### Integration simulation context

Read all of the above, plus:
- Task statuses from `yoke epic-tasks list`
- Worktree authorities from `epic_tasks` and `epic_dispatch_chains`: `task_num`, branch/worktree, and `worktree_path`
- Reviews from `yoke workflow-item epic-task review-get`
- Incomplete-task exclusions if `--force-integration`

Integration mode defaults to compressed two-phase mode unless `sim_force_standard_integration=true` in config:

```bash
_force_standard=$(python3 -m yoke_core.domain.runtime_settings get sim_force_standard_integration false)
```

If `_force_standard` is `true`, set `_use_compressed=false`. Otherwise set `_use_compressed=true`.

Compute and log the scope estimate for observability:

```bash
_pflight_tasks=$(python3 -m yoke_core.domain.runtime_settings get sim_preflight_task_threshold 8)
_pflight_kb=$(python3 -m yoke_core.domain.runtime_settings get sim_preflight_size_kb 20)
_body_bytes=0
_review_bytes=0
_diff_bytes=0
```

Include task bodies, reviews, spec, plan, and diff stat sizes in the log line.

### Compressed integration bundle

When `_use_compressed=true`, build:
- Interface contracts per task
- Worktree authorities per task
- File overlap matrix
- Dependency edge list
- Per-task change summaries
- Diff stats per branch
- Review summaries

### Standard integration bundle

When `_use_compressed=false`, gather worktree lane authorities plus full `git diff main...{branch}` output for each worktree branch in the plan. The task worktree checkout is the authority for unmerged task state whether there is one lane or many; main is the base/integration target.

## 4. Invoke The Simulator

Use the canonical prompts in [dispatch-prompts.md](dispatch-prompts.md):
- Plan simulation prompt
- Standard integration prompt
- Compressed integration prompt

Select the prompt that matches the detected phase and `_use_compressed` mode.

## 5. Capture Ouroboros Reflections

Search the Simulator response for text between `---REFLECTION-START---` and `---REFLECTION-END---`.

For each reflection entry found, write it to the DB:

```bash
cat << 'ENTRY_EOF' | yoke ouroboros entry insert --stdin \
 --timestamp "{timestamp}" \
 --agent "{agent}" \
 --context "{context}" \
 --category "{category}"
{body text}
ENTRY_EOF
```

If no reflection delimiters are found, continue silently.

## 6. Save The Gap Report To DB

Write the Simulator's gap report via `simulation-upsert`:

```bash
echo "{gap_report_content}" | yoke workflow-item epic-task simulation-upsert --epic "{epic-id}" --phase {phase} --stdin
```

Where `{phase}` is `plan` or `integration`.

Write the report even if the result is clean.

## 7. Parse And Display Summary

Count severity prefixes in the report:
- `[CRITICAL]`
- `[WARNING]`
- `[NOTE]`

Display:

```text
Simulation complete ({phase} phase): {X} critical, {Y} warnings, {Z} notes

{if X > 0:}
Critical gaps require resolution before proceeding.

{if X == 0 and Y > 0:}
No critical gaps. Review warnings and decide whether to fix or accept.

{if X == 0 and Y == 0:}
Clean simulation. Safe to proceed.

Report stored in DB. To read: python3 -m yoke_core.cli.db_router epic simulation-get "{epic-id}" "{phase}"
```

If `[CRITICAL]` or `[WARNING]` gaps remain and the operator wants auto-fix, continue with [autofix-loop.md](autofix-loop.md).

# Dispatch Context — Prompt Templates

Extracted from `dispatch-context.md`. Engineer and Tester prompt templates and dispatch rules.

---

## 5g. Engineer Prompt Template

**Dispatch ALL Engineers in parallel** (excluding tasks where `_has_implementation_${_task_id}` is true) -- issue one Agent tool call per task in `_task_ids` in the same response. For epic task fan-out, `YOK-{N}` / `_epic_id` is the parent item and `_task_id` is the local epic task number; do not render task prompts as `YOK-{_task_id}`.

**Dispatch:** descriptor `DispatchDescriptor(role="engineer")` rendered via `yoke_core.domain.dispatch_descriptors.render_for_harness(descriptor, harness_id)`, one rendered dispatch per task in the parallel batch. Result-schema markers: `---SUBMISSION-CHECKS-START---`, `---REFLECTION-START---`. The descriptor's `prompt: |` block is filled with:
```
# For each task in _task_ids, dispatch simultaneously with the rendered descriptor:
 Implement YOK-{N} task {_task_id}: {task title}

	 {context block from 5f-issue.2 or 5f-epic.6}

	 Read the authoritative task spec from the DB before starting:
	 yoke workflow-item epic-task body-get --epic {_epic_id} --task-num {_task_id}

 {If _anticipated_paths_block_{_task_id} is non-empty:}
 Anticipated path coverage (pre-authorized):
 {_anticipated_paths_block_{_task_id}}

 {If _rehydration_block_{_id} is non-empty:}
 {_rehydration_block_{_id}}

 {For every project-owned item — include this block:}
 Project Test Commands:
 Quick: {_cmd_quick}
 Full: {_cmd_full}
 E2E: {_cmd_e2e}
 Smoke: {_cmd_smoke}
 Ephemeral URL: {_ephemeral_url}

	 IMPORTANT: cd to the worktree path FIRST before doing any work.
	 Acceptance criteria are in the spec.
	 Commit incrementally on the worktree branch.
	 Run tests before finishing. If Project Test Commands are provided above, use those instead of guessing CLI invocations.

	 CODEBASE-READER NAMING: Assume future readers of the codebase will NOT have the ephemeral planning artifacts you are working from. Treat the task/spec/plan as scaffolding, not naming source material. New or renamed files, modules, helpers, tests, docs, commands, events, config keys, symbols, headings, and comments must describe current function, purpose, mechanics, or domain role to someone who can only see the repository. Do not copy ticket IDs, plan names, initiative labels, phase/task/thread numbers, AC/FR identifiers, branch/worktree names, or implementation-batch wording into live code or current-state docs unless the identifier is itself a runtime/domain concept.

	 {If task body/spec mentions schema, column, migration, ALTER TABLE, CREATE TABLE, ADD COLUMN, or DROP TABLE:
	 DB MIGRATION PROTOCOL: This task involves schema changes. You MUST follow the migration protocol in your agent definition (## DB Schema Changes section). Key steps: use the source-dev backup helper BEFORE any DDL, then update the project registry, Doctor, db-reference.md, and registered `yoke` wrappers. The lint hook will block unacknowledged DDL in `yoke db read` (which is read-only).}

 {If task body/spec mentions live DB, verify, CHECK constraint, deployed state, or any shared mutable system:
 LIVE-STATE AC FAIL-SAFE: ACs tagged [READ-ONLY] mean observe and report only — do NOT fix mismatches. ACs tagged [APPLY-MUTATION] mean apply the change via the sanctioned write path. Untagged ACs that reference live/shared state MUST be treated as [READ-ONLY] — do NOT mutate. Report ambiguity in your structured output. See your agent definition (## Live-State AC Execution Semantics) for full details.}

 OUTPUT DISCIPLINE: Before final response, write a final progress note containing the required `---SUBMISSION-CHECKS-START---` block from your agent definition. Then return only a short summary (commit count, test status). Do not repeat spec text or acceptance criteria in your final output.
```

### Anticipated Path Coverage block sourcing

The `_anticipated_paths_block_{_task_id}` slot above is **derived from existing persisted task data**, not from a new storage surface. Conduct reads the task body (`yoke workflow-item epic-task body-get --epic {_epic_id} --task-num {_task_id}`) and looks for a per-task `## Anticipated Paths` block authored by the Architect during plan (see `runtime/agents/architect.md` § *Anticipation Checklist*). When present, conduct inlines that block under the `Anticipated path coverage (pre-authorized)` heading in the Engineer prompt; when absent, the slot is empty and the heading is elided. The Architect's read-only anticipation helper `yoke_core.domain.architect_plan_anticipation` makes the underlying grep discipline cheap — conduct still consumes the persisted result, never recomputes it at dispatch time.

---

## 5i. Tester Dispatch — Diff Preparation and Dispatch Rules

**No manual diff truncation.** When constructing Tester prompts, NEVER manually truncate or summarize diffs with `...` or similar shorthand. Either inline the full diff (if under the size-gate threshold) or externalize to a temp file and pass the file path. Manual `...` summaries force the Tester to re-read the full file anyway, wasting turns, and risk omitting critical context. All Tester prompt content blocks MUST go through the size-gate mechanism below — no exceptions.

**Per-task diff size-gate constant:**
```
TESTER_DIFF_INLINE_MAX_LINES=300
```
When a per-task or per-attempt diff exceeds this threshold, write it to a temp file and pass `--stat` summary plus file path instead of inlining. This prevents context saturation that causes Tester timeouts and no-verdict failures.

**Compact diff capture:** Construct each Tester prompt in a single step -- read the diff, build the prompt, and dispatch. Do not store large diffs in intermediate shell variables. If the diff exceeds 500 lines (for issue items the 300-line TESTER_DIFF_INLINE_MAX_LINES threshold applies first), pass a summary stat line and the file path instead of inlining.

**Context-minimal output handling:** When Testers return, extract only the verdict (PASS/FAIL from DB or text). Write reflections to DB immediately (step 5m). Store `_tester_feedback` only for FAILED items needing retry (and only the feedback text, not the full Tester output).

**Dispatch ALL Testers in parallel** -- issue one Agent tool call per task in the same response. Pre-dispatch, prepare diffs with each task's own worktree:

For each epic task, compute the per-task diff (size-gated) and write the full diff to a temp file:
```bash
# For each task in _task_ids:
_path_var="_worktree_path_${_task_id}"
_worktree_path="${!_path_var}"
_task_baseline_var="TASK_BASELINE_${_task_id}"
TASK_BASELINE="${!_task_baseline_var}"

# Size-gate the per-task diff (FR-1)
_task_diff_line_count_{_id}=$(git -C "${_worktree_path}" diff "${TASK_BASELINE}..HEAD" | wc -l | tr -d ' ')
if [ "$_task_diff_line_count_{_id}" -gt "$TESTER_DIFF_INLINE_MAX_LINES" ]; then
 _task_diff_file_{_id}=$(mktemp)
 git -C "${_worktree_path}" diff "${TASK_BASELINE}..HEAD" > "$_task_diff_file_{_id}"
 _task_diff_stat_{_id}=$(git -C "${_worktree_path}" diff "${TASK_BASELINE}..HEAD" --stat)
else
 _task_diff_{_id}=$(git -C "${_worktree_path}" diff "${TASK_BASELINE}..HEAD")
fi

# Full branch diff always written to temp file (FR-5)
_full_diff_file_{_id}=$(mktemp)
git -C "${_worktree_path}" diff main...HEAD > "$_full_diff_file_{_id}"
```
For issue items, compute the full diff with size-gate:
```bash
# For each issue item:

# Size-gate the full diff — for issues, the full diff IS the per-task diff (FR-3)
_full_diff_line_count_{_id}=$(git -C "${_worktree_path}" diff main...HEAD | wc -l | tr -d ' ')
if [ "$_full_diff_line_count_{_id}" -gt "$TESTER_DIFF_INLINE_MAX_LINES" ]; then
 _full_diff_file_{_id}=$(mktemp)
 git -C "${_worktree_path}" diff main...HEAD > "$_full_diff_file_{_id}"
 _full_diff_stat_{_id}=$(git -C "${_worktree_path}" diff main...HEAD --stat)
else
 _full_diff_{_id}=$(git -C "${_worktree_path}" diff main...HEAD)
fi
```

**Per-attempt retry diff size-gate:** On retry attempts (`_attempt > 1`), apply the same size-gate to the per-attempt diff:
```bash
# For each item on retry (_attempt > 1):
_attempt_baseline_var="ATTEMPT_BASELINE_${_task_id}"
ATTEMPT_BASELINE="${!_attempt_baseline_var}"
_attempt_diff_line_count_{_id}=$(git -C "${_worktree_path}" diff "${ATTEMPT_BASELINE}..HEAD" | wc -l | tr -d ' ')
if [ "$_attempt_diff_line_count_{_id}" -gt "$TESTER_DIFF_INLINE_MAX_LINES" ]; then
 _attempt_diff_file_{_id}=$(mktemp)
 git -C "${_worktree_path}" diff "${ATTEMPT_BASELINE}..HEAD" > "$_attempt_diff_file_{_id}"
 _attempt_diff_stat_{_id}=$(git -C "${_worktree_path}" diff "${ATTEMPT_BASELINE}..HEAD" --stat)
else
 _attempt_diff_{_id}=$(git -C "${_worktree_path}" diff "${ATTEMPT_BASELINE}..HEAD")
fi
```

### Epic Item Tester Prompt Template

(conduct-specific; shared context fields documented in `shared/tester-dispatch-template.md`)

**Dispatch:** descriptor `DispatchDescriptor(role="tester")` rendered via `yoke_core.domain.dispatch_descriptors.render_for_harness(descriptor, harness_id)`. Result-schema markers: `VERDICT: PASS|FAIL`, `---REFLECTION-START---`. The descriptor's `prompt: |` block is filled with:
```
 Validate YOK-{N} task {_task_id}: {task title}

 Sprint: {SPRINT} | Track: {TRACK}

	 Read the authoritative task spec from the DB before validating:
	 yoke workflow-item epic-task body-get --epic {_epic_id} --task-num {_task_id}

 {For epics only — include this block verbatim:}
 Epic DB identifiers (use these EXACTLY for review-insert; pass the report via --body-file <path>):
 epic-id: {_epic_id}
 task-num: {_task_id}

 {For epics: interface contracts from dependency tasks}
 {For epics: downstream task bodies for path-tracing}

 {For every project-owned item — include this block:}
 Project Test Commands:
 Quick: {_cmd_quick}
 Full: {_cmd_full}
 E2E: {_cmd_e2e}
 Smoke: {_cmd_smoke}
 Ephemeral URL: {_ephemeral_url}

 {If per-task diff was NOT size-gated (_task_diff_{_id} exists):}
 Engineer's changes for this task (diff from task start):
 {_task_diff_{_id}}

 {If per-task diff WAS size-gated (_task_diff_file_{_id} exists):}
 Engineer's changes for this task ({_task_diff_line_count_{_id}} lines, diff from task start):
 {_task_diff_stat_{_id}}
 Per-task diff ({_task_diff_line_count_{_id}} lines) written to: {_task_diff_file_{_id}}
 Read this file for line-level detail.

 {On retry where per-attempt diff was NOT size-gated (_attempt_diff_{_id} exists):}
 Engineer's changes this attempt only (diff from attempt start):
 {_attempt_diff_{_id}}

 {On retry where per-attempt diff WAS size-gated (_attempt_diff_file_{_id} exists):}
 Engineer's changes this attempt only ({_attempt_diff_line_count_{_id}} lines):
 {_attempt_diff_stat_{_id}}
 Per-attempt diff ({_attempt_diff_line_count_{_id}} lines) written to: {_attempt_diff_file_{_id}}
 Read this file for line-level detail.

 Full branch diff (all tasks from main) is available at: {_full_diff_file_{_id}}
 Read this file only if you need cross-task context for your review.

 Regression detection: When checking "no regressions" or "existing tests
 still pass," compare failing test NAMES between main and the branch —
 not just counts. A test that passes on main but fails on the branch is
 a regression even if total failure counts match. See step 5a in the
 Tester agent definition for the full procedure.

	 Review the engineer's work against the acceptance criteria in the spec.
	 Check codebase-reader naming: new or renamed surfaces must describe current function/purpose/mechanics rather than the ticket, plan, phase, task, AC, branch, worktree, or batch that produced them.
	 Run tests. Return a verdict line:
 VERDICT: PASS or VERDICT: FAIL followed by details.

 OUTPUT DISCIPLINE: End with VERDICT line and a brief summary. Do not echo the full spec or diff back.
```

### Issue Item Tester Prompt Template

(canonical source for conduct; see also `shared/tester-dispatch-template.md` for the portable version used by advance and other flows)

**Dispatch:** descriptor `DispatchDescriptor(role="tester", extras=(("model","opus"),) if _tester_output_failures_{_id} >= 2 else ())` rendered via `yoke_core.domain.dispatch_descriptors.render_for_harness(descriptor, harness_id)`. Result-schema markers: `VERDICT: PASS|FAIL`, `---REFLECTION-START---`. The descriptor's `prompt: |` block is filled with:
```
 Validate YOK-{_id}: {_title}

 Sprint: {SPRINT} | Track: {TRACK}

 Read the authoritative task spec from the DB before validating:
 yoke items get YOK-{_id} spec

 {For every project-owned item — include this block:}
 Project Test Commands:
 Quick: {_cmd_quick}
 Full: {_cmd_full}
 E2E: {_cmd_e2e}
 Smoke: {_cmd_smoke}
 Ephemeral URL: {_ephemeral_url}

 {If full diff was NOT size-gated (_full_diff_{_id} exists):}
 Engineer's changes (full diff from main):
 {_full_diff_{_id}}

 {If full diff WAS size-gated (_full_diff_file_{_id} exists):}
 Engineer's changes ({_full_diff_line_count_{_id}} lines, full diff from main):
 {_full_diff_stat_{_id}}
 Full diff ({_full_diff_line_count_{_id}} lines) written to: {_full_diff_file_{_id}}
 Read this file for line-level detail.

 {On retry where per-attempt diff was NOT size-gated (_attempt_diff_{_id} exists):}
 Engineer's changes (this attempt only):
 {_attempt_diff_{_id}}

 {On retry where per-attempt diff WAS size-gated (_attempt_diff_file_{_id} exists):}
 Engineer's changes this attempt only ({_attempt_diff_line_count_{_id}} lines):
 {_attempt_diff_stat_{_id}}
 Per-attempt diff ({_attempt_diff_line_count_{_id}} lines) written to: {_attempt_diff_file_{_id}}
 Read this file for line-level detail.

	 Regression detection: When checking "no regressions" or "existing tests
	 still pass," compare failing test NAMES between main and the branch —
	 not just counts. A test that passes on main but fails on the branch is
	 a regression even if total failure counts match. See step 5a in the
	 Tester agent definition for the full procedure.

	 Review the engineer's work against the acceptance criteria in the spec.
	 Check codebase-reader naming: new or renamed surfaces must describe current function/purpose/mechanics rather than the ticket, plan, phase, task, AC, branch, worktree, or batch that produced them.
	 Run tests. Return a verdict line:
 VERDICT: PASS or VERDICT: FAIL followed by details.

 OUTPUT DISCIPLINE: End with VERDICT line and a brief summary. Do not echo the full spec or diff back.
```

**AUTONOMOUS CONTINUATION REQUIRED:** The subagent has returned. IMMEDIATELY continue to the next step below. Do NOT stop, do NOT wait for user input, do NOT generate a conversational summary and pause. Emit a one-line checkpoint: `[CONTINUE] Tester returned for YOK-{N}. Next: verdict processing (step 5j)` — then execute that step.

**Post-Tester cleanup:** After each Tester returns and reflections/artifacts are captured (steps 5m, 5n), clean up all temp files:
```bash
# For each item after Tester returns:
rm -f "$_full_diff_file_{_id}" # Epic/Issue: full branch diff temp file
rm -f "$_task_diff_file_{_id}" # Epic: per-task diff temp file
rm -f "$_attempt_diff_file_{_id}" # Both: per-attempt retry diff temp file
```

---
## 5i-minimal
<!-- Extracted to dispatch-context-prompts-minimal.md — see that file for the full minimal Tester prompt variant. -->

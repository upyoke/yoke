# Dispatch Context — Prompt Templates

Extracted from `dispatch-context.md`. Engineer prompt template, Tester diff preparation, and shared dispatch rules.

---

## 5g. Engineer Prompt Template

**Dispatch ALL Engineers in parallel** (excluding tasks where `_has_implementation_${_task_id}` is true) -- issue one Agent tool call per task in `_task_ids` in the same response. For epic task fan-out, `PREFIX-{N}` / `_epic_id` is the parent item and `_task_id` is the local epic task number; do not render task prompts as `PREFIX-{_task_id}`.

**Dispatch:** descriptor `DispatchDescriptor(role="engineer")` rendered via `yoke_core.domain.dispatch_descriptors.render_for_harness(descriptor, harness_id)`, one rendered dispatch per task in the parallel batch. Result-schema markers: `---SUBMISSION-CHECKS-START---`, `---REFLECTION-START---`. The descriptor's `prompt: |` block is filled with:
```
# For each task in _task_ids, dispatch simultaneously with the rendered descriptor:
 Implement PREFIX-{N} task {_task_id}: {task title}

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

	 CODEBASE-READER NAMING: Assume future readers of the codebase will NOT have the ephemeral planning artifacts you are working from. Treat the task/spec/plan as scaffolding, not naming source material. New or renamed files, modules, helpers, tests, docs, commands, events, config keys, symbols, headings, and comments must describe current function, purpose, mechanics, or domain role to someone who can only see the repository. Do not copy work item IDs, plan names, initiative labels, phase/task/thread numbers, AC/FR identifiers, branch/worktree names, or implementation-batch wording into live code or current-state docs unless the identifier is itself a runtime/domain concept.

	 {If task body/spec mentions schema, column, migration, ALTER TABLE, CREATE TABLE, ADD COLUMN, or DROP TABLE:
	 DB MIGRATION PROTOCOL: This task involves schema changes. You MUST follow the migration protocol in your agent definition (## DB Schema Changes section). Key steps: use the source-dev backup helper BEFORE any DDL, then update the project registry, Doctor, db-reference.md, and registered `yoke` wrappers. The lint hook will block unacknowledged DDL in `yoke db read` (which is read-only).}

 {If task body/spec mentions live DB, verify, CHECK constraint, deployed state, or any shared mutable system:
 LIVE-STATE AC FAIL-SAFE: ACs tagged [READ-ONLY] mean observe and report only — do NOT fix mismatches. ACs tagged [APPLY-MUTATION] mean apply the change via the sanctioned write path. Untagged ACs that reference live/shared state MUST be treated as [READ-ONLY] — do NOT mutate. Report ambiguity in your structured output. See your agent definition (## Live-State AC Execution Semantics) for full details.}

 OUTPUT DISCIPLINE: Before final response, write a final progress note containing the required `---SUBMISSION-CHECKS-START---` block from your agent definition. Then return only a short summary (commit count, test status). Do not repeat spec text or acceptance criteria in your final output.
```

### Anticipated Path Coverage block sourcing

The `_anticipated_paths_block_{_task_id}` slot above is **derived from existing persisted task data**, not from a new storage surface. Conduct reads the task body (`yoke workflow-item epic-task body-get --epic {_epic_id} --task-num {_task_id}`) and looks for a per-task `## Anticipated Paths` block authored by the Architect during plan (see the Architect prompt's *Anticipation Checklist*). When present, conduct inlines that block under the `Anticipated path coverage (pre-authorized)` heading in the Engineer prompt; when absent, the slot is empty and the heading is elided. The Architect's read-only anticipation helper `yoke_core.domain.architect_plan_anticipation` makes the underlying grep discipline cheap — conduct still consumes the persisted result, never recomputes it at dispatch time.

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

### Tester prompt construction

Read and render [the shared Tester template](../shared/tester-dispatch-template.md)
for both item and generated-task validation. It owns the descriptor, required
QA/project context, task review identity, diff slots, verdict, and naming checks.
Use the per-task variables prepared above for each batch member; include its
context block, dependency interfaces, downstream task bodies, and retry diff.
Do not build a separate Conduct prompt.

**AUTONOMOUS CONTINUATION REQUIRED:** The subagent has returned. IMMEDIATELY continue to the next step below. Do NOT stop, do NOT wait for user input, do NOT generate a conversational summary and pause. Emit a one-line checkpoint: `[CONTINUE] Tester returned for PREFIX-{N}. Next: verdict processing (step 5j)` — then execute that step.

**Post-Tester cleanup:** After each Tester returns and reflections/artifacts are captured (steps 5m, 5n), clean up all temp files:
```bash
# For each item after Tester returns:
rm -f "$_full_diff_file_{_id}" # Epic/Issue: full branch diff temp file
rm -f "$_task_diff_file_{_id}" # Epic: per-task diff temp file
rm -f "$_attempt_diff_file_{_id}" # Both: per-attempt retry diff temp file
```

---
## 5i-minimal
<!-- Extracted to dispatch-context-prompts-minimal.md — see that adapter for the shared minimal Tester variant. -->

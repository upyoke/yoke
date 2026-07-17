# Dispatch Context — Artifacts and QA Lifecycle

Extracted from `dispatch-context.md`. Contains artifact formats, output capture, QA lifecycle management, and commit patterns used during and after dispatch.

**Watcher capture paths.** When conduct invokes a Yoke watcher (`watch_pytest`, `watch_merge`, `watch_doctor`, `watch_advance`, `watch_lifecycle`, `watch_session_offer`) the raw + progress captures land under the helper-resolved `<scratch_root>/watcher-captures/` — they are minted by `yoke_core.domain.project_scratch_dir.mint_watcher_capture_pair(...)` (or `watcher_capture_path(...)` for one stream) and the wrapper prints the resolved paths through `--print-streaming-pair`. Read the path the wrapper printed; do not hardcode an OS-temp watcher-capture literal in dispatch artifacts. The operator carve-out for pinning the capture file is `--raw-capture <path>` (CI / artifact collection).

---

## Anticipated path coverage (pre-authorized)

When the Architect declares each task's path-claim, the plan-time **Anticipation Checklist** (`runtime/agents/architect.md` § *Anticipation Checklist*) widens claim coverage to include cross-cutting surfaces beyond the explicit File Budget — doctor HCs that scan the module, transitive callers, and deeper test importers. The Architect persists the resulting anticipated-paths set as a per-task `## Anticipated Paths` block in the task body. The read-only helper `yoke_core.domain.architect_plan_anticipation.build_anticipation_list` produces the categorised list that backs that block.

The Engineer prompt template surfaces this block under the heading `Anticipated path coverage (pre-authorized)` (see `dispatch-context-prompts.md` step 5g). It is **read-only context for the Engineer**:

- The set comes from existing persisted task body content. No new DB column, event type, function id, or storage surface is introduced for this surfacing.
- Conduct, the Engineer, the Tester, and downstream phases do **not** mutate the anticipated-paths list. Mid-implementation discoveries that fall outside it still route through the Engineer's commit-time claim-widening discipline; cross-task or new-surface discoveries route back to `/yoke refine`.
- When a task body has no `## Anticipated Paths` block (older plans, simple non-cross-cutting tasks), conduct omits the heading from the dispatch prompt entirely — there is no "empty section" placeholder.

---

## 5m. Ouroboros Reflection Capture

**Claude (primary harness): captured automatically by the PostToolUse Agent-tool hook** at `yoke_core.domain.reflection_capture_hook`. No skill-body action required — the hook reads the subagent's full `tool_response`, runs the multi-shape parser, persists entries to `ouroboros_entries`, and emits `ReflectionCaptureHookFired` (always) plus `ReflectionCaptureHookUnhandled` (when an unrecognized shape appears).

**Codex (parity capture): subagent dispatch is the custom-agent path** (`.codex/agents/yoke-*.toml`), not an in-process `Agent` tool call. The PostToolUse `Agent` matcher does not fire on Codex. When `$YOKE_EXECUTOR=codex` AND the conduct session has just received a subagent response, run the operator/debug CLI to capture the reflection block before continuing the next step:

```bash
if [ "${YOKE_EXECUTOR:-}" = "codex" ]; then
    _project=$(yoke items get "YOK-${_id}" project 2>/dev/null || echo yoke)
    printf '%s' "$_subagent_response" | python3 -m yoke_core.domain.reflection_capture \
        --default-agent "$_role" \
        --project "$_project" || true
fi
```

Where `$_subagent_response` is the captured subagent response text (the same text the conduct flow already reads to dispatch the next phase), `$_role` is the canonical agent role (`engineer`, `tester`, `simulator`, etc.), and `$_id` is the in-flight item id. The Codex-conditional shape keeps Claude sessions on the hook path (zero skill-body action) while restoring deterministic capture for Codex.

`python3 -m yoke_core.domain.reflection_capture --output-text ...` remains the operator/debug CLI for both harnesses — call it directly when ad-hoc backfilling lost reflections.

---

## 5n. Tester Artifact Commit

After the Tester returns, check if any files were created in the worktree and commit them so the later merge/polish handoff does not fail on a dirty worktree:

```bash
cd {_worktree_path}
git add -A 2>/dev/null
git diff --cached --quiet || git commit -m "chore: commit Tester review artifacts [YOK-${_id}]"
```

**Note:** Reviews and Ouroboros reflections are written directly to the DB, not to the worktree filesystem. This catches any other filesystem artifacts the Tester may have created.

---

## Epic-Task QA Lifecycle

Conduct owns the full epic-task QA gate lifecycle. Standard sessions use registered `yoke qa ...` and `yoke workflow-item epic-task ...` surfaces; direct DB-router QA calls are operator-debug only.

### Automatic QA Seeding

Before each epic-task `reviewing-implementation` transition, conduct calls:
```bash
yoke workflow-item epic-task review-seed --epic "$_epic_id" --task-num "$_task_id"
```
This idempotently creates a single blocking `implementation_review` requirement for the task. The Tester's verdict (via `review-insert`) reuses this requirement rather than creating a new one.

### Tester Verdict Recording

The Tester writes its verdict via `yoke workflow-item epic-task review-insert`, which:
1. Finds the existing review requirement (seeded above) — does NOT create a duplicate
2. Records a `qa_run` with the Tester's verdict against that requirement

### Parent Epic Reviewed-Implementation Gate

After all tasks pass and integration simulation succeeds, conduct satisfies any unsatisfied parent-item-level verification requirements from conduct evidence before advancing the parent to `reviewed-implementation`.

### Recovery Commands

If a conduct session is interrupted and you need to manually recover:
```bash
# Seed a review requirement for a task (idempotent):
yoke workflow-item epic-task review-seed --epic "{epic_id}" --task-num {task_num}

# Record a Tester verdict for a task — write the body to a file first, then pass --body-file:
yoke workflow-item epic-task review-insert --epic "{epic_id}" --task-num {task_num} --verdict PASS --body-file /tmp/yoke-review.{task_num}.md

# List requirements for an epic (filter to the task_num client-side):
yoke qa requirement list --epic-id "{epic_id}"

# Do NOT use `yoke qa run add` (or db_router qa run-add) for epic-task review verdicts:
# yoke workflow-item epic-task review-insert is the only supported write path.
# The --body-file form is the taught path; stdin fallback remains supported for callers
# that cannot land a tempfile (the lint blocks plain heredoc/pipe shapes through that adapter).
```

---

## QA Quick Reference (for conduct orchestrator)

**HARD RULE: NEVER auto-waive blocking QA requirements.** If a blocking requirement (`blocking_mode='blocking'`) cannot be satisfied (e.g., no ephemeral URL for browser QA, test infrastructure unavailable), **HALT immediately** and ask the operator to either:
1. Waive manually through the retained operator-debug waiver path with `--source operator --force`
2. Fix the underlying issue (e.g., deploy the ephemeral environment, fix test infra)

The retained internal QA waiver path **rejects waiving blocking requirements without `--force`**. It is operator-debug only; do not present it as the normal product QA flow. Non-blocking requirements can still be waived without `--force`. Always include `--source operator` when the operator explicitly authorizes a waiver, or `--source agent` for automated non-blocking waivers.

When the conduct orchestrator needs to interact with QA tables directly (e.g., waiving non-blocking requirements, recording runs for the `reviewed-implementation` gate), use these exact flags:

```bash
# Waive a NON-BLOCKING requirement through the retained operator-debug waiver path:
db_router qa requirement-waive {requirement-id} "Rationale text" --source agent

# Waive a BLOCKING requirement (ONLY when operator explicitly authorizes):
db_router qa requirement-waive {requirement-id} "Rationale text" --source operator --force

# Record a passing non-review QA run (NOT for simulation — use yoke workflow-item epic-task simulation-upsert instead):
yoke qa run add --requirement-id {req-id} --executor-type "agent" --qa-kind "ac_verification" --verdict "pass" --raw-result "Brief evidence"

# List requirements for an item:
yoke qa requirement list --item "YOK-{N}"

# List runs for a requirement:
yoke qa run list --requirement-id {req-id}
```

**Required flags for `yoke qa run add`:** `--requirement-id`, `--executor-type`. Optional: `--qa-kind` (defaults to the requirement's stored kind; mismatch is a hard error), `--verdict`, `--execution-status`, `--raw-result`, `--duration-ms`. Multi-line evidence or score/confidence fields stay on the retained operator-debug `db_router qa run-add` fallback.

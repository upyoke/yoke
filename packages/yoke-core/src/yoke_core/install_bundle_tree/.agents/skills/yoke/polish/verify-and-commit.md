# Polish — Verify And Commit

Covers polish steps 8 and 9: run verification against the fixes, then commit.

**Context variables** (set by earlier phases): `ITEM_NUM`, `WORKTREE_PATH`, `WORKTREE_PATHS`.

---

## 8. Run Verification

After applying fixes, run the project's registered test commands, if configured:

```bash
MAIN_ROOT=$(git rev-parse --show-toplevel)
ITEM_NUM=$(printf '%s' "{arg}" | sed 's/^[Ss][Uu][Nn]-//; s/^0*//')
ITEM_PROJECT=$(yoke items get "$ITEM_NUM" project 2>/dev/null) || true
CMD_QUICK=$(python3 -m yoke_core.domain.command_definitions get "$ITEM_PROJECT" quick 2>/dev/null) || true
CMD_FULL=$(python3 -m yoke_core.domain.command_definitions get "$ITEM_PROJECT" full 2>/dev/null) || true
```

Verification expectations:
- If `CMD_QUICK` is configured, run it from each worktree that received fixes. For a single-worktree item, this is `{WORKTREE_PATH}`. For a multi-worktree epic, iterate the changed paths from `WORKTREE_PATHS`.
- **Polish MUST run `CMD_QUICK` (or `CMD_FULL` when `CMD_QUICK` is absent) for any project whose `command_definitions.quick` is configured, regardless of which files the fixes touched.** This is the load-bearing local-verification surface the merge gate substitutes when no required CI checks are configured (classifier + reader live in `runtime/api/domain/item_test_results_classify.py`). The agent-judgment "shared infrastructure" carve-out is removed for projects with a registered quick command — they always run pytest. Projects without a registered quick command keep the carve-out: run `CMD_FULL` when the touched files span shared infrastructure, core routing, or multiple subsystems.
- **Polish MUST write the captured pytest output to `items.test_results` whenever it runs `CMD_QUICK` or `CMD_FULL` — stamped with the worktree HEAD SHA and written AFTER the step-9 commit.** The capture artifact already lives at `/tmp/yoke-cmd.XXXXXX` per the capture-first rule in AGENTS.md `## Command Output — Hard Rule`. Hold the captured output here and perform the actual write in **step 9b** (below), once any polish fix is committed, so the stamped SHA is the branch tip usher will merge. The polish→implemented gate (`runtime/api/domain/db_mutation_gate_polish.py::check_polishing_implementation_to_implemented_gate`) refuses the transition when the project has a `command_definitions.quick` configured and `items.test_results` is empty or carries a failure verdict — the structural backstop for this mandate; the **freshness-bound** merge gate (`runtime/api/engines/merge_worktree_pr.py`) is the second line of defense at usher time, and it now refuses a PASS verdict whose stamped SHA does not match the PR head SHA. That is why the write carries the HEAD-SHA trailer and happens last.
- If no project test command is configured (no `CMD_QUICK` and no `CMD_FULL`), run the most relevant changed tests directly from the worktree that changed.
- When you modify tests themselves, re-run those tests explicitly even if a broader quick command also exists.
- When the polish pass touched prompt surfaces or large scripts, re-run any relevant doctor or invariants checks that cover line-count/consistency drift in addition to the normal project tests. **Always invoke doctor through the watcher wrapper** (`python3 -m yoke_core.tools.watch_doctor -- --quick`) — per AGENTS.md `## Command Output — Hard Rule`, every doctor run goes through the watcher to avoid the `2>&1 > file` redirection trap that silently strips stderr to the void. **Always pass `--quick`** — polish never needs the GitHub-dependent HCs and `--quick` skips them. Without an explicit scope flag the engine refuses to run (exit code 2); without `--quick` it burns gh quota every polish and contributes to GraphQL rate-limit exhaustion downstream at usher's `pr-create`.

The captured output is written to `items.test_results` in **step 9b** below (after the commit, with the HEAD-SHA trailer appended) — not here.

**Verdict format the polish gate parses:** `runtime/api/domain/item_test_results_classify.py` accepts two pytest pass-verdict shapes as first-class evidence:
- **Banner mode** (`pytest` default): the literal `=== N passed in TIMEs ===` banner with surrounding equals signs.
- **Quiet mode** (`pytest -q`): a standalone `N passed in TIMEs` verdict line (the `in TIMEs` clause is optional).

The classifier recognises either shape with no failure-token interference; uppercase `FAILED` / `ERROR` / `ERRORS` still beats any pass count. Prose verdicts like "all tests passed" or "9/9 passing" — anything without a numeric `N passed` line — classify as `empty` and the gate refuses the transition. The watcher wrappers (`watch_pytest`) preserve whichever shape pytest emitted in their raw capture, so the recommended path is to paste the wrapper's full raw capture rather than a hand-written summary.

If tests fail after fixes, investigate and fix. Do not leave the worktree in a failing state. Future/planned item ownership or a planned path claim is not a waiver for current-item verification failures. If a failing test points at a file outside the current claim, use the sanctioned path-claim workflow (`path-claim-widen` plus dependency or claim reconciliation when required) and fix it in this branch; only a live active-session conflict or an explicit operator waiver can block the repair. Do not use `path-claim-override` for a planned future claim when dependency or claim reconciliation can resolve the ordering; override is last resort for irreducible live collisions and requires explicit operator approval.

## 9. Commit

If any files were changed during polish, commit with a descriptive message:

```bash
git -C "{worktree-path}" add {specific changed files}
git -C "{worktree-path}" commit -m "polish: {brief description of finishing fixes} (YOK-{N})"
```

Use a scoped `git add` of the files you actually changed. For multi-worktree epics, make a separate commit in each worktree that changed, and leave untouched worktrees untouched. Do not use `git add -A` unless every dirty file in that worktree belongs to this polish pass.

If no changes were needed, skip the commit and note that the implementation was already clean.

**Do NOT push the branch or create a pull request.** Pushing and PR creation are usher's responsibility. Polish only commits locally to the worktree.

## 9b. Record The Test Verdict (head-SHA bound)

After the step-9 commit (or immediately, if no polish fix was needed), capture the worktree HEAD SHA and write the held pytest output to `items.test_results` with the SHA trailer appended. This binds the verdict to the exact commit usher will merge: the freshness-bound merge gate (`runtime/api/engines/merge_worktree_pr.py`) accepts a PASS as a CI substitute **only** when the stamped SHA matches the PR head SHA, so an unstamped or stale verdict blocks the merge with an actionable message. Make NO further commits after this write — the stamped SHA must stay the branch tip.

```bash
VERDICT_SHA=$(git -C "{worktree-path}" rev-parse HEAD)
```

Append the trailer to the held pytest capture on its own line, then write the combined content. The trailer is an HTML comment, so it never perturbs the verdict classifier (`runtime/api/domain/item_test_results_classify.py`) — a PASS still classifies PASS and an uppercase `FAILED`/`ERROR` still beats the pass count. The trailer shape has one source of truth: `format_verdict_head_sha_trailer(head_sha)` in that module renders exactly `<!-- yoke-verdict-head-sha: <sha> -->`.

```jsonc
{
  "function": "items.structured_field.replace",
  "actor":  {"session_id": "<this-session>"},
  "target": {"kind": "item", "item_id": <N>},
  "payload": {
    "field": "test_results",
    "content": "<full pytest capture + verdict line>\n\n<!-- yoke-verdict-head-sha: <VERDICT_SHA> -->"
  }
}
```

# 5i-minimal. Minimal Tester Prompt Variant (No Inline Diff)

Extracted from `dispatch-context-prompts.md`. Used by the Tester output gate after the first empty output.

This prompt variant does NOT inline the git diff, leaving maximum context budget for the Tester to read files directly and run tests. Used by `engineer-tester-closeout.md` Step 9 when the Tester output gate retries after an empty or unparseable verdict.

**When to use:** On Tester output gate retry 1 (`_tester_output_failures == 1`) and retry 2 (`_tester_output_failures == 2`, with `model: "opus"`). The initial Tester dispatch (step 5i) uses the full prompt with the diff inlined or externalized to a temp file via the diff size-gate described in `dispatch-context-prompts.md`.

**Watcher capture paths.** Any test-run captures the Tester produces via a Yoke watcher wrapper (pytest, merge, doctor, advance, deploy, lifecycle, session-offer) land at the helper-resolved location minted by `yoke_core.domain.project_scratch_dir.mint_watcher_capture_pair(...)` under `<scratch_root>/watcher-captures/` — read the path the wrapper prints rather than constructing an OS-temp literal. Operator carve-out for a pinned capture is `--raw-capture <path>`.

**Changed file list:** Before dispatching with this prompt, compute the list of changed files:
```bash
_changed_files=$(git -C "${_worktree_path}" diff --name-only main...HEAD)
```

**Prompt template:**

**Dispatch:** descriptor `DispatchDescriptor(role="tester", extras=(("model","opus"),) if _tester_output_failures >= 2 else ())` rendered via `yoke_core.domain.dispatch_descriptors.render_for_harness(descriptor, harness_id)`. Result-schema markers: `VERDICT: PASS|FAIL`, `---REFLECTION-START---`. The descriptor's `prompt: |` block is filled with:
```
	 Validate YOK-{N} task {_task_id}: {task title}

 IMPORTANT: Your previous invocation produced no parseable verdict.
 This is a minimal-prompt retry — no inline diff is provided.
 You have maximum context budget for file reads and test execution.

 Worktree path: {_worktree_path}
 Main repo root: {MAIN_ROOT}

	 Read the authoritative task spec from the DB before validating:
	 yoke workflow-item epic-task body-get --epic "{_epic_id}" --task-num "{_task_id}"

 Changed files (read these directly from the worktree):
 {_changed_files}

 {For non-yoke projects — include this block:}
 Project Test Commands:
 Quick: {_cmd_quick}
 Full: {_cmd_full}
 E2E: {_cmd_e2e}
 Smoke: {_cmd_smoke}
 Ephemeral URL: {_ephemeral_url}

 Instructions:
 1. cd to the worktree path above
 2. Read each changed file directly to understand the implementation
 3. Run the test suite and any acceptance-criteria tests from the spec
 4. For regression checks: compare failing test NAMES between main and
 the branch — not just counts. See step 5a in the Tester agent
 definition for the full procedure.
 5. Manage your context budget carefully — read only what you need
 6. Write the review body to a tempfile with the Write tool (e.g. `/tmp/yoke-review.{_task_id}.md`), then insert the review row via `yoke workflow-item epic-task review-insert --epic "{_epic_id}" --task-num "{_task_id}" --verdict <pass|fail> --body-file /tmp/yoke-review.{_task_id}.md`. The conduct-side closeout check rejects the verdict if no review row lands.
 7. Include VERDICT: PASS or VERDICT: FAIL in your response

 This is mandatory — the conduct loop cannot proceed without
 a deterministic verdict.
```

**Context budget target (NFR-3):** This prompt template should remain under 2000 tokens (excluding the spec body which the Tester reads at runtime via the DB command). The omission of the inline diff is the key space saving.

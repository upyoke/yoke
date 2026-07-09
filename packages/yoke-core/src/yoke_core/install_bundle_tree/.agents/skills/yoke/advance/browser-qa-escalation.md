# Advance — Browser QA: Orchestrator, Evaluation, and Escalation

Extracted from `browser-qa.md`. Covers manual screenshot fallback, browser orchestrator invocation, result evaluation, and screenshot evidence checks. Read and follow this file when `browser-qa.md` directs you here.

**Context variables** (inherited from router): `{N}`, `_item_project`, `_wt_branch`, `_eph_url`, `_head_sha`

---

## Manual Screenshot Fallback (step 5d.c-fallback)

If step 5d.c exits non-zero or exits 0 without linking any `qa_artifacts`, do NOT use raw SQL. Capture a manual screenshot with `yoke qa browser screenshot "$_eph_url{route}" --output <path.png>` (launcher token — starts the machine-local daemon on demand, works from any project checkout), then record a passing `browser_substrate` run for `{REQ_KIND}` via `yoke qa run add --requirement-id <id> --executor-type browser_substrate --verdict pass` followed by `yoke qa artifact add --requirement-id <id> --run-id <run_id> --artifact-type screenshot --content-type image/png --artifact-handle '{"backend":"local","path":"<abs-path.png>"}'` (or presign+upload first via `yoke qa artifact presign` and record the returned s3 handle — see advance/browser-qa-fallback.md). Continue to step 5d-eval after the artifact is linked.

Detailed command templates live in `advance/browser-qa-fallback.md`.

## Invoke Browser Orchestrator (step 5d.c)

> **Streaming carve-out:** the orchestrator invocation is intentionally captured in a single `$(...)` block rather than routed through `yoke_core.tools.watch_*`. The downstream evaluation parses structured JSON from `_orchestrator_result` (capture run id, screenshot paths) and the orchestrator runs in seconds-to-tens-of-seconds with progress that lives inside its own structured event log, not as agent-stream lines. The agent never sees the orchestrator's stream until it completes, so the flooding class does not apply here. If browser QA orchestration ever exceeds that bound, the right fix is a structured-event-aware watcher — out of scope for this gate.

The launcher shape works from ANY project checkout (DB legs route through `qa.browser_context.get` / `qa.run.add` / `qa.run.complete` / `qa.artifact.add`, https included). Recording runs requires the session's active work-claim on the item.

```bash
_orchestrator_result=$(yoke qa browser run \
 --item {N} --project "$_item_project" --base-url "$_eph_url" \
 --expected-branch "$_wt_branch" --expected-sha "$_head_sha" 2>&1)
_orch_exit=$?
```

## Evaluate Result (step 5d.d)

- **Exit 0:** Mechanical assertions passed → continue to screenshot evaluation below
- **Exit 1:** Scenario failed → **block**, show output. Gate is re-entrant.
- **Exit 2:** Prerequisite failure → **block**, show troubleshooting

## Screenshot Evaluation (step 5d-eval)

**Only runs when orchestrator exited 0.** Run two independent checks and require both to pass:
1. **Visible-defect scan:** fail any screenshot a human would call visibly broken, even if it matches the ACs.
2. **AC consistency check:** fail any screenshot that contradicts, or is too generic to prove, the ACs.

**a.** Extract screenshot paths from orchestrator JSON output.

**b.** Read item ACs:
```bash
_item_body=$(yoke items get {N} body 2>/dev/null) || true
_item_acs=$(printf '%s' "$_item_body" | sed -n '/^## Acceptance Criteria/,/^## /{ /^## /d; p; }') || true
```

**Screenshot-evidence completeness gate.** Before skipping evaluation, check whether the item has unsatisfied `requires_screenshot_evidence` requirements:
```bash
_sse_json=$(yoke qa screenshot-evidence pending-count --item {N} --json)
_sse_unsatisfied=$(printf '%s' "$_sse_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['pending_count'])")
```

If `_sse_unsatisfied` is non-empty and greater than 0 and no screenshots were produced → **hard-block**:
> **Blocked:** YOK-{N} has {_sse_unsatisfied} unsatisfied `requires_screenshot_evidence` AC requirement(s) but no screenshot evidence was produced. Verify screenshot-producing actions and daemon artifact paths, then re-run the same `/yoke advance YOK-{N} <target>` boundary after fixing.

Do NOT update status. Do NOT call `qa screenshot-evidence satisfy`. **Stop.**

If `_sse_unsatisfied` is 0 or empty, and no screenshots or no ACs → skip evaluation, proceed to finalize.

**c.** Read each screenshot image (Read tool) and answer:
1. Is anything visibly broken even if the ACs look satisfied? Examples: raw escaped text or HTML entities, broken or missing images, overlap or clipping, layout collapse or overflow, missing fonts or tofu boxes, blank sections, exception overlays, or garbled placeholder text.
2. Does the screenshot prove the AC changes? Check for required evidence, visible contradictions, and "could this pass on any version of the page?" false positives.

**d.** If either check fails, do NOT call `qa screenshot-evidence satisfy`. Flip the verdict on the **existing** capture run so gates that filter `verdict='pass'` correctly see the failure, and **block**:
```bash
# inspection writes verdict onto the capture row (same run_id) via
# qa.run.complete. This preserves the one-row-per-capture audit trail and
# emits QARunCompleted at the real inspection moment — not at capture time.
# The orchestrator surfaces the capture run_id + requirement_id in its
# stdout JSON at .runs[0]; parse from there rather than guessing by timestamp.
_capture_run_id=$(printf '%s' "$_orchestrator_result" | python3 -c "import json,sys; print(json.load(sys.stdin)['runs'][0]['qa_run_id'])")
_capture_req_id=$(printf '%s' "$_orchestrator_result" | python3 -c "import json,sys; print(json.load(sys.stdin)['runs'][0]['requirement_id'])")
yoke qa run complete \
 --requirement-id "$_capture_req_id" --run-id "$_capture_run_id" --verdict "fail" \
 --raw-result "Screenshot evaluation: {visible defect detected|AC contradiction} — {concrete description, e.g., 'raw Unicode escape sequences \\u2728 rendered as literal text in the hero section'}"
```

Use `visible defect detected` for Check 1 failures and `AC contradiction` for Check 2 failures.

**e.** Only when both checks pass, first flip the capture row's verdict to `pass` via `qa run complete` on the same `run_id`, then bridge the evidence. The bridge refuses (`capture_not_verified`) unless the matching capture row is now `execution_status='captured' AND verdict='pass'`:
```bash
# mark the capture inspection-verified before bridging.
_capture_run_id=$(printf '%s' "$_orchestrator_result" | python3 -c "import json,sys; print(json.load(sys.stdin)['runs'][0]['qa_run_id'])")
_capture_req_id=$(printf '%s' "$_orchestrator_result" | python3 -c "import json,sys; print(json.load(sys.stdin)['runs'][0]['requirement_id'])")
yoke qa run complete \
 --requirement-id "$_capture_req_id" --run-id "$_capture_run_id" --verdict "pass" \
 --raw-result "Screenshot evaluation passed — no visible defects, screenshots consistent with acceptance criteria"

# bridge screenshot evaluation pass to ac_verification requirements.
_sse_json=$(yoke qa screenshot-evidence satisfy --item {N} --json \
 --evidence "Browser QA screenshot evaluation passed — no visible defects, screenshots consistent with acceptance criteria")
_sse_count=$(printf '%s' "$_sse_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['satisfied_count'])")
```

If `_sse_count` is non-empty and greater than 0:
> Satisfied {_sse_count} screenshot-evidence AC requirement(s) via browser QA evaluation. Browser QA passed. No visible defects detected; screenshots consistent with acceptance criteria.

Do NOT update status on failure. Gate is re-entrant.

---

After browser QA passes, return to router for finalize phase.

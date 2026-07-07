# Advance — Project E2E Gate

Called by the advance router when target is `reviewed-implementation`, `implemented`, or `polishing-implementation`. Runs the project's configured `e2e` scope of the `command_definitions` family against the ephemeral deployment. Skip if target is not one of those three statuses.

**E2E tests exercise a real deployed backend.** The four-tier test model defines the `e2e` scope as a real end-to-end suite — frontend → backend → database — run against a deployment, not against mocked APIs. Browser integration tests with mocked APIs belong under the `full` scope (typically `npm run test:browser`). Shallow real-stack checks belong under the `smoke` scope and run from the deploy pipeline's `smoke` stage, not from this gate.

Because E2E hits a real backend, this gate injects the ephemeral URL (or, when configured, a staging URL) via `BASE_URL` so the suite targets the deployment that matches the current worktree.

**Context variables** (set by router): `{N}`, `_item_project`, `SCRIPT_DIR`

**This gate is re-entrant:** Retrying the same `/yoke advance YOK-{N} <target>` boundary re-executes the E2E command. A new passing run satisfies the gate.

---

## Check Unsatisfied E2E Requirements (step 5e.a)

Use the typed `yoke qa gate-summary` surface (function id `qa.gate_summary.run`; works over https) — same target semantics as the gate, no raw QA SQL needed here:

```bash
_qa_target="reviewed-implementation"
[ "{_target}" = "implemented" ] && _qa_target="implemented"
[ "{_target}" = "polishing-implementation" ] && _qa_target="implemented"
_qa_summary_json=$(yoke qa gate-summary --item "YOK-{N}" --target "$_qa_target")
_unsatisfied_e2e=$(printf '%s' "$_qa_summary_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['e2e_unsatisfied_count'])")
```

If `0`, skip — no blocking E2E requirements or all satisfied. Proceed to finalize.

## Resolve E2E Command (step 5e.b)

```bash
_item_project=$(yoke items get {N} project 2>/dev/null) || true
_e2e_cmd=""
if [ -n "$_item_project" ] && [ "$_item_project" != "null" ]; then
 # Source-dev/admin read: populate _e2e_cmd from the command_definitions
 # Project Structure family. No registered product CLI wrapper exists yet.
fi
```

If `_e2e_cmd` is empty → skip with advisory:
> **Advisory:** Project '{_item_project}' has no `e2e` command defined in `command_definitions` (no real E2E suite) — skipping project E2E gate.

Do NOT block. Proceed to finalize. (This is the path Buzz takes today: browser integration tests live under the `full` scope, and real E2E is not yet configured.)

## Resolve Project Repo Path (step 5e.c)

```bash
_e2e_repo=$(yoke projects get --project "$_item_project" --field repo_path 2>/dev/null) || true
_e2e_repo=${_e2e_repo:-$(git rev-parse --show-toplevel)}

# Prefer worktree if it exists. E2E runs against issue items only (epics have no
# single worktree; their tasks each have their own lane resolved via conduct).
_e2e_item_type=$(yoke items get {N} type 2>/dev/null) || true
_e2e_dir="$_e2e_repo"
if [ "$_e2e_item_type" != "epic" ]; then
 _wt_branch=$(yoke items get {N} worktree 2>/dev/null) || true
 if [ -n "$_wt_branch" ] && [ -d "$_e2e_repo/.worktrees/$_wt_branch" ]; then
 _e2e_dir="$_e2e_repo/.worktrees/$_wt_branch"
 fi
fi
```

## Resolve Ephemeral URL for BASE_URL Injection (step 5e.d)

Real E2E runs against a deployed backend. Look up the ephemeral environment this branch is pointed at so the suite can target it via `BASE_URL`. Uses the same `ephemeral_environments` query shape as `shared/tester-dispatch-template.md` section 5.

```bash
_base_url=$(python3 -m yoke_core.cli.db_router query \
 "SELECT url FROM ephemeral_environments \
 WHERE project_id=(SELECT id FROM projects WHERE slug='${_item_project}') \
 AND branch='YOK-{N}' \
 AND url IS NOT NULL AND url <> '' AND url <> 'pending' \
 ORDER BY id DESC LIMIT 1" 2>/dev/null) || true
```

If `_base_url` is empty → the ephemeral deployment has not produced a URL yet. **Block** with a re-entrant advisory:
> **Blocked:** Project E2E requires a deployed backend but no ephemeral URL is available for `YOK-{N}` in project '{_item_project}'.
>
> Wait for the ephemeral deployment workflow to finish (it publishes the URL into `ephemeral_environments.url`), then retry the same `/yoke advance YOK-{N} <target>` boundary.

Do NOT update status. The gate is re-entrant and will pick up the URL once it lands.

## Resolve Playwright Cache (step 5e.e)

Export the same `PLAYWRIGHT_BROWSERS_PATH` that worktree setup used, so Playwright
finds the installed browser binaries at runtime. The source of truth is the
worktree domain helper that owns `resolve_playwright_cache()`; this remains a
Yoke source-dev/admin helper with no registered product CLI wrapper.

```bash
# Source-dev/admin read: populate _pw_cache for "$_item_project" and "$_e2e_dir".
_pw_export=""
if [ -n "$_pw_cache" ]; then
 _pw_export="PLAYWRIGHT_BROWSERS_PATH=$_pw_cache"
fi
```

Surface the resolved path for diagnostics:
> **Playwright cache:** `{_pw_cache}` (resolved via the source-dev/admin worktree cache helper)

If `_pw_cache` is empty:
> **Playwright cache:** using Playwright default (no project ID or worktree path)

## Run E2E Command Against Deployment (step 5e.f)

Run the configured command with `BASE_URL` injected so the E2E suite targets the ephemeral deployment.

> **Streaming carve-out:** the E2E command is intentionally captured in a single `$(...)` invocation rather than routed through `yoke_core.tools.watch_*`. The orchestrator parses the full output downstream (truncated tail goes into the QA-run raw-result column on failure — see your `qa_runs` packet stanza), and per-project E2E commands have heterogeneous progress shapes (Playwright, vitest, custom shell pipelines) that no single watcher classifier covers today. Buffered capture remains the right contract here: the command runs synchronously, its progress never reaches the agent stream until completion, and the agent only consumes the final pass/fail plus last 100 lines. If a future project E2E suite produces flooded output before completion, the right fix is a `command_definitions`-aware generic watcher — out of scope for this gate.

```bash
_e2e_env="BASE_URL=$_base_url"
if [ -n "$_pw_export" ]; then
 _e2e_env="$_e2e_env $_pw_export"
fi

_e2e_output=$(cd "$_e2e_dir" && env $_e2e_env sh -c "$_e2e_cmd" 2>&1)
_e2e_exit=$?
```

Surface target and command:
> **Project E2E:** Running `{_e2e_cmd}` against `BASE_URL={_base_url}` from `{_e2e_dir}`...

## Record QA Run and Evaluate (step 5e.g)

Get the E2E requirement ID from the cached summary captured in step 5e.a (lowest-id unsatisfied e2e requirement, matching the original SQL ORDER BY id ASC LIMIT 1):
```bash
_e2e_req_id=$(printf '%s' "$_qa_summary_json" | python3 -c "import json,sys; reqs=json.load(sys.stdin)['requirements']; print(next((r['id'] for r in reqs if r['qa_kind']=='e2e' and not r['satisfied']), ''))")
```

### On success (exit 0):

Record passing run:
```bash
yoke qa run add \
 --requirement-id "$_e2e_req_id" \
 --executor-type "ci" \
 --qa-kind "e2e" \
 --verdict "pass" \
 --raw-result "E2E suite passed against ${_base_url}"
```

> **Project E2E passed.** All tests passed against `{_base_url}`.

Proceed to finalize.

### On failure (non-zero exit):

Record failing run:
```bash
# Truncate output to last 100 lines for storage
_truncated_output=$(printf '%s' "$_e2e_output" | tail -100)

yoke qa run add \
 --requirement-id "$_e2e_req_id" \
 --executor-type "ci" \
 --qa-kind "e2e" \
 --verdict "fail" \
 --raw-result "E2E suite failed (exit $_e2e_exit) against ${_base_url}: ${_truncated_output}"
```

**Block** the transition:
> **Blocked:** Project E2E tests failed against `{_base_url}`.
>
> Exit code: {_e2e_exit}
>
> Output (last 100 lines):
> ```
> {_truncated_output}
> ```
>
> Fix the failing tests (or redeploy the ephemeral environment) and retry the same `/yoke advance YOK-{N} <target>` boundary.

Do NOT update status. Gate is re-entrant.

---

After project E2E passes, return to router for finalize phase.

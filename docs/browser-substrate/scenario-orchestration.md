# Scenario Orchestration

The scenario orchestrator (`yoke_core.domain.browser_qa`) is the canonical entry point for executing browser QA scenarios against a running ephemeral environment. It is used by both the direct advance path (standalone items) and the conduct path (epic items) -- there is no parallel implementation. Browser execution (daemon, screenshots) runs on the invoking machine; every DB leg routes through the function-call dispatcher (`qa.browser_context.get`, `qa.run.add`, `qa.run.complete`, `qa.artifact.add`), so the flow works identically inside a Yoke checkout and from an external project over the https relay.

Lives under [browser-substrate.md](../browser-substrate.md); cross-link back from there for the daemon, ref system, and step-executor primitives that scenarios consume.

## Usage

Agent shape (works from any project checkout; tool-shaped launcher token):

```sh
yoke qa browser run --item PREFIX-N [--project P] [--base-url URL] \
    [--expected-branch BRANCH --expected-sha SHA]
```

Checkout-dev module form is an internal source-dev entry point with the same flags and numeric item ids. Do not teach it as an agent recipe; agents use the `yoke qa browser run` launcher above.

## What It Does

1. **Fetches the scenario context** via one `qa.browser_context.get` call: the item's unwaived `browser_smoke` / `browser_diff` requirements plus the freshness row, with public item refs resolved server-side
2. **Resolves `base_url`** from `--base-url` flag or from the requirement's `success_policy.base_url`
3. **Validates reachability** of the target URL (DNS resolution + HTTP probe). Fails with a clear error and the URL if unreachable, rather than timing out silently
4. **Ensures daemon is running** -- auto-starts the browser daemon if not already active
5. **Iterates each requirement's `success_policy.steps`**, executing each step sequentially via `yoke_core.domain.browser_client exec step`
6. **Records a `qa_run`** per requirement (via `qa.run.add` / `qa.run.complete`) with `executor_type='browser_substrate'`. On capture success the row lands with `execution_status='captured', verdict=NULL` — no quality claim is made yet. On capture failure it lands with `execution_status='capture_failed', verdict='fail'` so existing verdict-filtering gates still treat it as unsatisfied
7. **Records `qa_artifact`** entries (via `qa.artifact.add`) for screenshots produced during execution. Artifact recording failures fail the entire run (no silent swallowing)
8. **Outputs a JSON summary** on stdout: `{"verdict":"pass|fail","runs":[...]}`. Each entry in `runs` carries `qa_run_id`, `execution_status`, `verdict`, and `artifacts` so the advance/escalation skill can drive the later inspection step

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All scenarios passed |
| 1 | At least one scenario failed |
| 2 | Prerequisite failure (unreachable URL, no requirements, daemon failure, context fetch failure) |

## Re-Entrancy

The orchestrator is re-entrant. Retrying `/yoke advance YOK-N implemented` after a failed browser scenario re-executes the orchestrator. A fresh capture writes a new `browser_substrate` row with `execution_status='captured'`; the gate advances only once inspection flips verdict to `pass` on one of those rows via `yoke qa run complete --requirement-id <id> --run-id <capture_run_id> --verdict pass`. The gate check (`yoke_core.domain.qa_gates`) looks for at least one `browser_substrate` run with `verdict='pass'` per requirement — by construction that means an inspected, quality-approved capture.

## Executor Type Enforcement

`yoke qa run add` rejects `executor_type='agent'` for `browser_smoke` and `browser_diff` kinds at write time. Only `executor_type='browser_substrate'` runs (produced by this orchestrator, or by the manual fallback path in `advance/browser-qa-fallback.md`) satisfy the gate for browser QA requirements.

## Capture vs Inspection Verdict

`qa_runs.verdict='pass'` on a `browser_smoke` / `browser_diff` row means **inspection approved**, not "the daemon ran." Capture success alone records `execution_status='captured'` with a NULL verdict. The escalation skill (`advance/browser-qa-escalation.md`) runs screenshot inspection after capture and calls `yoke qa run complete --requirement-id <id> --run-id <capture_run_id> --verdict pass|fail` to flip verdict in place. Only then does `yoke qa screenshot-evidence satisfy` bridge into `ac_verification` — the guard (`capture_not_verified`) refuses otherwise.

## Execution Paths

Both paths converge on the same orchestrator. There is no parallel implementation.

### Path 1: Direct Advance (standalone items)

When a standalone item (not part of an epic's conduct cycle) advances toward `implemented`:

1. The browser QA gate in `advance/browser-qa.md` detects unsatisfied browser QA requirements
2. It resolves the ephemeral URL from `ephemeral_environments` for the item
3. It invokes `yoke qa browser run --item N --project P --base-url URL`
4. The orchestrator executes scenarios, records `qa_runs` and `qa_artifacts`
5. The orchestrator surfaces the ephemeral URL to the operator for manual review
6. `yoke_core.domain.qa_gates` finds the passing `browser_substrate` run and allows the transition

### Path 2: Conduct (epic items)

During conduct (Tester phase), the Tester agent:

1. Reads `qa_requirements` for the item and finds `browser_smoke`/`browser_diff` requirements with structured scenarios in `success_policy`
2. Optionally refines scenario steps (replacing placeholder selectors, adding interaction steps, marking `refined: true`), persisting refined scenarios back to `qa_requirements.success_policy`
3. Invokes the same `yoke_core.domain.browser_qa` orchestrator with the item's ephemeral URL
4. The orchestrator writes results to `qa_runs` and `qa_artifacts` (not a legacy `reviews` table)
5. Both the Tester's review verdict AND the orchestrator's `qa_runs` evidence must exist for the item to advance

**Important:** The Tester's review verdict (stored as a `qa_runs` row linked to a `qa_requirements` review requirement) and the orchestrator's `qa_runs` records are independent. The review is the Tester's overall assessment. The `qa_runs` records are substrate evidence. `yoke_core.domain.qa_gates` checks for `browser_substrate` runs without bridging through a legacy `reviews` surface.

## Artifact Storage Convention

The orchestrator stores artifacts under project scratch storage, organized by
item ID and run ID:

```
{scratch_root}/{project}/storage/qa-artifacts/{item_id}/{run_id}/screenshot-{step_index}-{timestamp}.png
```

Example: `/tmp/yoke-scratch/external-webapp/storage/qa-artifacts/941/87/screenshot-0-20260317-143022.png`

The capture directory is non-durable scratch. Durability is opt-in at the
record boundary: for each on-disk capture the orchestrator mints a presigned
PUT through `qa.artifact.presign` (server-side: resolves
`environments.settings.artifacts.bucket` for the project — requirement
`target_env` first, then `prod`, then name-sorted — and signs with the
project's `aws-admin` capability credentials), uploads over plain HTTPS, and
records the returned typed handle via `qa.artifact.add`:

```json
{"backend": "s3", "bucket": "{project}-{env}-artifacts",
 "key": "qa-artifacts/{project}/{item_id}/{run_id}/screenshot-{step_index}-{timestamp}.png"}
```

When no environment declares a bucket (or the upload fails), the orchestrator
records an explicit local handle on the capture's absolute path instead:

```json
{"backend": "local", "path": "/abs/path/to/capture.png"}
```

Metadata recorded with each artifact includes:

| Field | Description |
|-------|-------------|
| `step_index` | Step index within the scenario |
| `qa_kind` | `browser_smoke` or `browser_diff` |
| `item_id` | The item being tested |

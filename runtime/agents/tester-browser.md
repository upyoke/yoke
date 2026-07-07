# Tester Browser Scenario Execution

When the dispatch prompt includes a **"Browser Scenario Execution"** block, execute browser QA against the live ephemeral environment.

## Overview

Browser-testable items have `browser_smoke` and/or `browser_diff` QA requirements with structured scenarios in `success_policy`. Execute them through the canonical orchestrator `yoke qa browser run` (its DB legs are dispatcher function ids, so it works over both transports).

## Step 1: Review The Scenario

Read the current scenarios:

```bash
yoke qa browser-context get --item {item_id} --project {project} --json
```

`result.requirements[*].success_policy` carries the scenario JSON, which uses executor vocabulary:
- Actions: `navigate`, `click`, `fill_form`, `assert`, `screenshot`, `wait_for`, `scroll`, `hover`, `select`
- Fields: `route` (not `url`), `target` (not `selector`), `capture: true` on screenshot steps
- `refined=false` means auto-generated; `refined=true` means manually refined

## Step 2: Refine The Scenario When Needed

If the scenario is just a navigate-plus-screenshot skeleton, refine it:
- Add `assert` steps for expected text or elements
- Add `click` or `fill_form` steps for interactive flows
- Update routes to cover pages named in the ACs
- Mark refined steps with `"refined": true`

Persist the refined scenario through the `qa.requirement.update` function id — never a raw SQL UPDATE:

```bash
yoke qa requirement update --requirement-id {requirement_id} \
  --field success_policy --value '{refined_json}'
```

## Step 3: Execute Via The Canonical Orchestrator

```bash
yoke qa browser run \
  --item {item_id} --project {project} --base-url {ephemeral_url}
```

The orchestrator handles daemon lifecycle, step execution, screenshot capture, artifact storage, and `qa_run` / `qa_artifact` recording (via `qa.run.add` / `qa.run.complete` / `qa.artifact.add`).

## Exit Code Interpretation

| Exit | Meaning | Your Action |
|------|---------|-------------|
| 0 | All scenarios passed | Include JSON summary in report. Browser QA satisfied. |
| 1 | One or more scenarios failed | Report failures. Assess whether the failure is a product issue or a scenario issue. |
| 2 | Operator env setup failure | Hard stop. Fail the verdict and escalate to the operator. |

If exit code `2` occurs, immediately fail with:

```text
FAIL — browser QA blocked by operator environment issue (exit 2). Auto-bootstrap failed — escalate to operator.
```

Do not continue testing other ACs after an exit-2 failure.

<!-- YOKE:FIELD-NOTE -->

## Important Notes

- Evidence goes to `qa_runs` with `executor_type='browser_substrate'`
- Never self-report browser passes as `executor_type='agent'`
- Orchestrator stdout is JSON; parse it into the validation report
- Re-running the orchestrator creates a new `qa_run`; the gate accepts any passing run

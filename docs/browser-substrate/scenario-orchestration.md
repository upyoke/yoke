# Browser Case Orchestration

The shared QA case runner is the canonical entry point for executing a
materialized Browser method case against a running ephemeral environment.
Direct Advance and Conduct/Tester use the same per-requirement path.

The Browser daemon and evidence capture run on the invoking machine. Control
plane reads and writes use registered function calls, so execution works from
the Yoke checkout and from a connected project checkout.

See [Browser Automation Substrate](../browser-substrate.md) for daemon, ref,
and step-executor primitives, and
[Browser Scenario Schema](../../.yoke/docs/browser-scenario-schema.md) for the
case configuration contract.

## Usage

Run one materialized requirement at a time:

```sh
yoke qa case run \
  --requirement-id <requirement-id> \
  --base-url "<environment-url>" \
  --expected-branch "<worktree-branch>" \
  --expected-sha "<worktree-head-sha>"
```

`--expected-branch` and `--expected-sha` are a required pair for Browser
delivery flows. They bind the evidence to the deployed code identity; do not
omit them to bypass freshness validation.

## Case authority

`qa.case_execution.begin` authorizes and returns the immutable materialized
case snapshot before any local Browser work. The runner selects Browser
execution from its registered executor and invokes the substrate for only the
named requirement.

Browser cases use one of two method IDs:

- `browser-check` runs declared assertions and produces an automatic verdict.
- `browser-inspection` captures evidence and produces an inconclusive verdict,
  which creates a review request for approval, rejection, or waiver.

The case's `method_config` is a JSON object with a non-empty `steps` array and
an optional `base_url`. Execution consumes this snapshot as-is. Tester and
Advance flows must not refine or replace it after materialization.

## What the runner does

1. Authorizes and fetches the named case through `qa.case_execution.begin`.
2. Resolves the target URL from `--base-url` or the case's
   `method_config.base_url`.
3. Validates URL reachability and checks the deployed branch and SHA against
   `--expected-branch` and `--expected-sha`.
4. Ensures the machine Browser substrate is ready and starts its daemon.
5. Executes each declared `method_config.steps` entry in order.
6. Records a run through `qa.run.add` and `qa.run.complete`.
7. Records screenshot or trace evidence through `qa.artifact.add`; durable
   storage uses `qa.artifact.presign` when the project environment declares an
   artifact bucket.
8. Prints a JSON result for the named requirement, including its verdict, run
   identity, execution status, and artifact paths.

The runner owns those run and artifact writes. Callers must not create a
parallel run or self-report Browser evidence as an agent verdict.

## Exit codes and verdicts

| Exit | Meaning |
|------|---------|
| `0` | Execution completed without a fail/error verdict. A Browser inspection can still be `inconclusive` and awaiting review. |
| `1` | The case verdict is `fail`. |
| `2` | A prerequisite, case-contract, freshness, or executor error prevented valid completion. |

A successful `browser-check` is immediately satisfied. A successful
`browser-inspection` capture remains unresolved until its generated review
request is approved, rejected, or waived.

## Re-entrancy

The case runner is re-entrant. Re-running a requirement records fresh evidence
without changing its materialized `method_config`. The transition gate accepts
the union of current blocking requirements: every requirement must have a
passing run or an explicit waiver.

## Execution paths

### Direct Advance

The gate in
[`.agents/skills/yoke/advance/browser-qa.md`](../../.agents/skills/yoke/advance/browser-qa.md)
materializes the transition plan, selects unsatisfied Browser method cases,
resolves the ephemeral URL and deployed code identity, then invokes `yoke qa
case run` once per requirement.

### Conduct / Tester

Conduct resolves the same URL, worktree branch, and worktree HEAD SHA before
dispatch. The Tester reads materialized requirements, selects unsatisfied
`browser-check` and `browser-inspection` cases, and invokes `yoke qa case run`
once per requirement with all freshness inputs. The Tester's overall review
and each requirement's recorded Browser evidence are separate gate inputs.

## Artifact storage

Browser captures are first written under project scratch storage:

```text
{scratch_root}/{project}/storage/qa-artifacts/{item_id}/{run_id}/screenshot-{step_index}-{timestamp}.png
```

When the target environment declares an artifact bucket, the runner uploads
the capture and records a durable handle:

```json
{"backend": "s3", "bucket": "{project}-{env}-artifacts",
 "key": "qa-artifacts/{project}/{item_id}/{run_id}/screenshot-{step_index}-{timestamp}.png"}
```

If durable upload is unavailable, it records an explicit machine-local handle:

```json
{"backend": "local", "path": "/absolute/path/to/capture.png"}
```

Artifact metadata includes the step index, requirement identity, route, item
identity, project, viewport, and timestamp.

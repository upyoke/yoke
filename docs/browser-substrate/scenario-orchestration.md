# Browser Case Orchestration

The shared QA case runner is the canonical entry point for executing a
materialized Browser method case against a running ephemeral environment.
Direct Advance and Conduct/Tester use the same per-requirement path.

The Browser daemon and evidence capture run on the invoking machine. Control
plane reads and writes use registered function calls, so execution works from
the Yoke checkout and from a connected project checkout.

See [Browser Automation Substrate](../browser-substrate.md) for daemon, ref,
and step-runner primitives, and
[Browser Scenario Schema](../../.yoke/docs/reference/browser-scenarios.md) for the
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

A case attached to a deployment run takes that expectation from the run
instead, and the arguments are unnecessary: the run records the commit it was
pinned to deliver, and that is what its evidence is judged against. Naming a
different commit for such a case refuses (`deployment_source_contradicted`)
rather than choosing one, and a run pinned to no commit refuses too
(`deployment_source_unpinned`) — there would be nothing for the environment's
own answer to be compared with.

Which deployment is asked comes from the case's own subject, never from the
branch alone. An item case is about that branch's preview, and is answered by
the recorded ephemeral environment or, when none exists, by the preview
publishing its own commit at the project's `ephemeral-env` `identity_path`. A
case attached to a deployment run is about the environment that run targeted,
and is answered by that environment publishing its own commit at the project's
`health-endpoint` `identity_path` beneath its registered url, read on every
check. Nothing stored substitutes for that reading: the lineage a run
*requested* is not proof of what it serves, and a deployment record — even one
that read the environment back — says what was served when that run deployed,
which a later release to the same environment silently outdates. Evidence may
then be collected only from the deployment that answered: browsing anywhere
else refuses before a browser starts.

## Case authority

`qa.case_execution.begin` authorizes and returns the immutable materialized
case snapshot before any local Browser work. The runner selects Browser
execution from its registered runner and invokes the substrate for only the
named requirement.

Browser cases use one of two method IDs:

- `browser-check` runs declared assertions and produces an automatic verdict.
  A check whose assertions never matched an element — every one of them an
  absence-shaped check against a zero-match locator — observed no page at all
  and fails as `assertion_vacuous_absence` rather than passing. See
  [browser scenarios](../public/reference/browser-scenarios.md).
- `browser-inspection` captures linked evidence and can produce an undetermined
  verdict with a reason naming what could not be established and why. That
  halts the item until a project owner/operator resolves its review request.

The case's `method_config` is a JSON object with a non-empty `steps` array and
an optional `base_url`. Execution consumes this snapshot as-is. Tester and
Advance flows must not refine or replace it after materialization.

## What the runner does

1. Authorizes and fetches the named case through `qa.case_execution.begin`.
2. Resolves the target URL from `--base-url` or the case's
   `method_config.base_url`.
3. Validates URL reachability with GET, a cookie jar, and same-origin
   redirects (so a review URL that exchanges a login token for an HttpOnly
   cookie is not a false 401), then checks the deployed branch and SHA against
   `--expected-branch` and `--expected-sha`. Genuine 401, timeout, TLS, and
   off-origin-redirect refusals still fail closed; probe errors never echo
   tokens or cookies.
4. Ensures the machine Browser substrate is ready and starts its daemon.
5. Opens the page this case owns, sized to `method_config.viewport` or to the
   default 1440x900, and closes it when the case ends. Every step names that
   page, so a case can neither inherit another case's route and width nor
   leave its own behind.
6. Executes `method_config.steps` in order until the first failed required
   step. It captures one diagnostic screenshot when the page is available,
   skips dependent steps, then runs any declared `cleanup_steps` (at most five)
   on the same page before closing it. A cleanup failure is added to the run
   errors without replacing the first failure.
7. Records a run through `qa.run.add` and `qa.run.complete`.
8. Records screenshot or trace evidence through `qa.artifact.add`; durable
   storage uses `qa.artifact.presign` with direct S3 or the hosted tenant broker
   when either is configured. A client that already holds the bytes can pass them
   inline (`content_base64` plus `filename`) instead of a machine-local
   handle the server cannot read.
9. Prints a JSON result for the named requirement, including its verdict, run
   identity, execution status, artifact paths, and any `vacuous_absences` —
   absence assertions that passed against a locator matching zero elements.

The runner owns those run and artifact writes. Callers must not create a
parallel run or self-report Browser evidence as an agent verdict.

## Exit codes and verdicts

| Exit | Meaning |
|------|---------|
| `0` | Execution completed without a fail/error verdict. A Browser inspection can still be `undetermined` and awaiting review. |
| `1` | The case verdict is `fail`. |
| `2` | A prerequisite, case-contract, freshness, or runner error prevented valid completion. |

A successful `browser-check` is immediately satisfied. An evidence-backed
`browser-inspection` can remain unresolved until its generated review request
is approved, rejected, or waived. Missing evidence is an execution failure
and creates no human review request.

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
{scratch_root}/{project}/storage/qa-artifacts/{subject}/{run_id}/screenshot-{step_index}-{timestamp}.png
```

`{subject}` is the requirement's own owner: its item id, or
`deployment-run-{run}` when a deployment run owns the requirement.

Before recording evidence, the runner uploads the capture to the configured
project artifact bucket and records a durable handle:

```json
{"backend": "s3", "bucket": "{project}-{env}-artifacts",
 "key": "{artifacts.prefix?}/qa-artifacts/{project}/{subject}/{run_id}/screenshot-{step_index}-{timestamp}.png"}
```

Only when no environment declares an artifact bucket does the server copy the
submitted bytes into permanent application data and record a local handle:

```json
{"backend": "local", "path": "~/.yoke/artifacts/{project}/{subject}/{run_id}/capture.png"}
```

Missing S3 credentials and upload failures remain explicit capture failures;
configured storage never silently downgrades to local disk.
Hosted `YOKE_QA_ARTIFACT_*` settings carry the broker URL, read-only token file,
bucket, and immutable tenant prefix; the container receives no AWS credentials.

Artifact metadata includes the step index, requirement identity, route, item
identity, project, and timestamp, plus what the page reported about itself
when the capture was taken: its effective `viewport` and its `observed_url`.
Those two are first-hand; `route` is the route the case asked for, so a
capture that drifted can be seen to have drifted rather than being described
by the request.

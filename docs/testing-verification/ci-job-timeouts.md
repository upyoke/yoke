# CI job timeouts (internal)

Every executable GitHub Actions job in this repository declares a literal
`timeout-minutes` in its workflow. A hung job ends with GitHub's normal timeout
failure instead of occupying the merge queue for the six-hour default.

GitHub does not permit that key on a job calling a reusable workflow.
The timeout belongs to each executable job in the called workflow.
The repository contract in `runtime/api/domain/test_ci_action_pins.py` inventories
all `.yml` and `.yaml` workflows, rejects a missing or invalid executable-job
limit, and requires callers to reference an existing local workflow whose jobs
are included in that inventory. The doctor's check-name inventory recognizes
job-level `name` regardless of whether the timeout or runner comes first. See
[GitHub's supported caller keywords](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations#supported-keywords-for-jobs-that-call-a-reusable-workflow).

## Sizing limits

Use completed job durations to size each executable job's YAML limit. Exclude
cancelled and skipped jobs; include successful and failed jobs. For matrices,
use the slowest variant. Double the observed maximum, add two minutes, and
round up to the next five minutes. Review the declared limit when normal
execution outgrows its headroom. The workflow YAML is the source of truth.

## Recovery

Inspect the timed-out job's log to identify the stalled step. Fix a hang
before rerunning the failed check. If the step was making normal progress
and the workload has grown, measure recent completed runs and raise that
job's timeout with headroom. Keep the limit on the executable job rather than
adding an unsupported key to a reusable-workflow caller.

The release bridge includes the time it awaits Platform's release, so its
limit covers the downstream run as well as its own setup. No timeout handler
converts a timed-out required job into a passing check.

The consumer advisory runs in its own workflow. A cancelled or timed-out
advisory remains visible as advisory evidence in that run and cannot change
the required `yoke-ci` conclusion adopted by QA. Do not reintroduce it as a
reusable job inside required CI: job-level `continue-on-error` does not isolate
a timeout cancellation from the caller's aggregate conclusion.

# CI job timeouts

Every executable GitHub Actions job in this repository declares a literal
`timeout-minutes` in its workflow. A hung job ends with GitHub's normal timeout
failure instead of occupying the merge queue for the six-hour default.

GitHub does not permit that key on a job calling a reusable workflow.
The timeout belongs to each executable job in the called workflow.
The repository contract in `runtime/api/domain/test_ci_action_pins.py` inventories
all `.yml` and `.yaml` workflows, rejects a missing or invalid executable-job
limit, and requires callers to reference an existing local workflow whose jobs
are included in that inventory. See
[GitHub's supported caller keywords](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations#supported-keywords-for-jobs-that-call-a-reusable-workflow).

## Sizing evidence

Measured on 2026-09-30 using GitHub's job `started_at` and `completed_at`
timestamps from the latest 20 completed runs of each workflow. Cancelled and
skipped jobs are excluded; successful and failed executions are included.
Reusable jobs are measured in their caller runs, and each matrix job uses the
slowest sampled variant. Conditional steps can skip inside a completed job;
these are observed execution times, not predictions of every future path.

Each limit doubles the observed maximum, adds two minutes, and rounds up to
the next five minutes. The value is stored once per executable job in YAML;
this table records its sizing evidence. Update the job's literal value using
new run durations when normal execution outgrows its headroom.

| Workflow | Executable job | Sampled maximum | Limit (minutes) | Maximum-duration run |
| --- | --- | ---: | ---: | --- |
| `browser-runtime-tests.yml` | `browser-runtime` | 0m 13s | 5 | [run](https://github.com/upyoke/yoke/actions/runs/36730846788) |
| `cla.yml` | `signature-check, train-pass-through` | 0m 10s | 5 | [run](https://github.com/upyoke/yoke/actions/runs/36736254936) |
| `consumer-compatibility-advisory.yml` | `advisory` | 7m 19s | 20 | [run](https://github.com/upyoke/yoke/actions/runs/36730846788) |
| `platform-release-bridge.yml` | `dispatch-platform-release` | 27m 49s | 60 | [run](https://github.com/upyoke/yoke/actions/runs/36735992027) |
| `yoke-build-artifacts.yml` | `build` | 1m 15s | 5 | [run](https://github.com/upyoke/yoke/actions/runs/36707804949) |
| `yoke-build-artifacts.yml` | `attest` | 0m 13s | 5 | [run](https://github.com/upyoke/yoke/actions/runs/36365745581) |
| `yoke-ci.yml` | `repo_contracts` | 0m 49s | 5 | [run](https://github.com/upyoke/yoke/actions/runs/36742381952) |
| `yoke-ci.yml` | `reuse_coverage` | 0m 15s | 5 | [run](https://github.com/upyoke/yoke/actions/runs/36739480815) |
| `yoke-ci.yml` | `test_shard` | 14m 20s | 35 | [run](https://github.com/upyoke/yoke/actions/runs/36737749024) |
| `yoke-ci.yml` | `container` | 1m 57s | 10 | [run](https://github.com/upyoke/yoke/actions/runs/36738760986) |
| `yoke-release.yml` | `validate-tag` | 0m 06s | 5 | [run](https://github.com/upyoke/yoke/actions/runs/36525337933) |
| `yoke-release.yml` | `release` | 0m 36s | 5 | [run](https://github.com/upyoke/yoke/actions/runs/36463330017) |
| `yoke-server-image.yml` | `validate-tag` | 0m 08s | 5 | [run](https://github.com/upyoke/yoke/actions/runs/36492688869) |
| `yoke-server-image.yml` | `build` | 2m 40s | 10 | [run](https://github.com/upyoke/yoke/actions/runs/36660843655) |
| `yoke-server-image.yml` | `assemble` | 0m 35s | 5 | [run](https://github.com/upyoke/yoke/actions/runs/36636131417) |
| `yoke-server-image.yml` | `attest` | 0m 11s | 5 | [run](https://github.com/upyoke/yoke/actions/runs/36492688869) |
| `yoke-server-image.yml` | `publish-tags` | 1m 12s | 5 | [run](https://github.com/upyoke/yoke/actions/runs/36326447123) |
| `yoke-tests-selection.yml` | `plan` | 1m 13s | 5 | [run](https://github.com/upyoke/yoke/actions/runs/36743099271) |
| `yoke-tests-selection.yml` | `selection` | 6m 32s | 20 | [run](https://github.com/upyoke/yoke/actions/runs/36743099271) |

## Recovery

Inspect the timed-out job's log to identify the stalled step. Fix a hang
before rerunning the failed check. If the step was making normal progress
and the workload has grown, measure recent completed runs and raise that
job's timeout with headroom. Keep the limit on the executable job rather than
adding an unsupported key to a reusable-workflow caller.

The release bridge includes the time it awaits Platform's release, so its
limit covers the downstream run as well as its own setup. No timeout handler
converts a timed-out required job into a passing check.

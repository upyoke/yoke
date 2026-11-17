# Full suite on Windows and macOS

Internal: for maintainers of the Yoke source repository.

Linux CI (`yoke-ci.yml`) owns the full suite's required verdict. The
on-demand `yoke-suite.yml` workflow runs the same suite on Windows
(`windows-2025`) and macOS (`macos-latest`) on the newest supported Python. It
is layer 1 (test suite) of the multi-OS CI model: one workflow per layer, the
OS as a matrix value. The required `windows-smoke` job is separate and
unchanged.

Nothing triggers it automatically: macOS runners stay out of automatic CI
(`runtime/api/cli/test_github_workflow_runner_routing.py`). Dispatch it on any
commit:

```text
yoke github-actions workflow dispatch upyoke/yoke yoke-suite.yml --ref main \
  --input sha=<commit> --request-id <stable id> \
  --correlation-input yoke_dispatch_id --project yoke
```

An empty `sha` tests the dispatched ref.

## How a run is laid out

A Linux `plan` job collects the suite once and publishes the same file groups
(`ci_shard_groups`) and exact-commit product wheels that `yoke-ci` uses
([CI shards](ci-shards.md)). Each OS then runs every shard with
`yoke_core.tools.ci_shards run`, so the matrix is OS × shard. There is no
container runtime on these runners: `yoke_core.tools.ci_suite_postgres start`
fetches the product's own pinned Postgres engine, starts the disposable test
cluster under the runner's temp directory and exports `YOKE_PG_DSN` to later
steps. Each shard uploads `pytest-output-<os>-<shard>` with its log and JUnit
report.

The free macOS runner pool caps concurrency, so macOS shards queue; read
runtime from each job's own start and finish times, not the run's wall clock.

## Known-failure baselines

Tests that do not pass yet on an OS are listed in
`runtime/known_failure_baselines/<os>.json` as
`{"<node id>": "<reason>"}`. Node ids are relative to the repository root with
`/` separators; an id without `[params]` covers every case of the test. The
workflow sets `YOKE_KNOWN_FAILURE_BASELINE=1`, and the
`runtime.known_failure_baseline` plugin then marks each listed test
`xfail(strict=True)` on that OS only. Local runs never apply a baseline.

The baselines only shrink:

- a listed test that still fails is reported as xfailed;
- a listed test that passes fails the run as `XPASS(strict)`: delete its
  entry in the change that fixed it;
- an unlisted failure fails the run as usual. Fix it, or add an entry with
  the reason when the fix is real work.

`tests/test_known_failure_baseline.py` refuses an entry with no reason or one
that names no test defined in a suite file.

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

Tests that do not pass yet on an OS are listed in the JSON files under
`runtime/known_failure_baselines/<os>/`, one `"<node id>": "<reason>"` entry
per line, grouped by test directory and split so each file stays inside the
line limit. Node ids are relative to the repository root with `/`
separators; an id without `[params]` covers every case of the test, and a bare
`path.py` names a module that cannot be imported on that OS. The workflow sets
`YOKE_KNOWN_FAILURE_BASELINE=1`, and the `runtime.known_failure_baseline`
plugin then applies that OS's entries. Local runs never apply a baseline.

The baselines only shrink:

- a listed test is `xfail(strict=True)`: a failure in its setup, call or
  teardown reports as xfailed;
- a listed test that passes every phase fails the run at teardown with
  `[XPASS(strict)] <node id> passed`: delete its entry in the change that
  fixed it;
- a listed module's import error reports as skipped; once it imports, each of
  its tests is a listed test;
- an unlisted failure fails the run as usual. Fix it, or add an entry with
  the reason when the fix is real work.

### Flaky tests

A test that fails in some runs and passes in others cannot be held by a
strict entry. List it by hand in `runtime/known_failure_baselines/flaky/<os>.json`
as `"<node id>": {"reason": ..., "feedback": <entry id>, "fix_item": "YOK-N"}`:
file a feedback note for it, promote that note to a fix item
(`yoke feedback promote ENTRY --title "Fix flaky TEST"`) and link the item to
the NATIVE-WINDOWS strategy document. A flaky test runs as
`xfail(strict=False)`, so neither its failures nor its passes decide the run.
Delete the entry when its fix item lands. A test cannot be on both lists.

### Recording

To refresh a baseline, download the `pytest-output-<os>-*` artifacts of one
or more runs (from each run's summary page) into one directory and record
them:

```text
yoke dev run -- python3 -m runtime.known_failure_baseline_record \
  --os windows --reports /tmp/suite-windows
```

The recorder reads each shard's JUnit report. A test that failed wherever it
ran becomes an entry with its failure message as the reason, an entry for a
test that passed is deleted, and the rest are kept. A test that both failed
and passed across the runs is printed as flaky and never recorded: a strict
entry cannot hold it, so file it for a fix. Review the diff before
committing. `tests/test_known_failure_baseline.py` refuses an entry with
no reason, or one that names no test or module defined in a suite file.

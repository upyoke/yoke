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
  --input sha=0123456789abcdef0123456789abcdef01234567 --request-id <stable-id> \
  --correlation-input yoke_dispatch_id --project yoke --wait 5400
```

Replace the example SHA with the commit you want to test. The CLI expands a
local commit-ish to its full SHA before sending it. For direct GitHub
dispatches, the plan resolves an abbreviated SHA from fetched repository
history. An empty `sha` tests the dispatched ref. The plan writes the full
tested commit to the GitHub run summary.

`--wait` reports the exact run's conclusion. If the wait times out, use
`yoke github-actions wait-run upyoke/yoke <run-id> --project yoke` with the
printed run ID. When a lane changes
`yoke-suite.yml`, dispatch on the published lane branch so Actions also
uses that branch's workflow definition.

Windows shards provision Git Bash and enable Developer Mode for symlinks.
Both native runners provision ripgrep before pytest. macOS also provisions
fish for the installer shell-context checks.

## How a run is laid out

A Linux `plan` job collects the suite once and publishes the same file groups
(`ci_shard_groups`) and exact-commit product wheels that `yoke-ci` uses
([CI shards](ci-shards.md)). Each OS then runs every shard with
`yoke_core.tools.ci_shards run`, so the matrix is OS × shard. There is no
container runtime on these runners: `yoke_core.tools.ci_suite_postgres start`
fetches the product's own pinned Postgres engine, starts the disposable test
cluster under the runner's temp directory and exports `YOKE_PG_DSN` to later
steps. Pytest writes thread tracebacks to the shard log when a test takes
longer than five minutes. The pytest step has an 18-minute timeout within
the 30-minute job budget so the upload step can still save
`pytest-output-<os>-<shard>` with the streamed log and any JUnit report.
The first Windows shard also repeats the repo picker and JavaScript contracts
five times and saves the traceback from a deliberately stalled pytest worker.
The plan retains modules skipped before import on its collection OS
so native runners still receive them, with conservative product-wheel fixture
affinity because their fixture closure cannot be imported on the plan host.
Coverage manifests name these collection skips explicitly; each test and each
module skip must appear exactly once in the shard reports.

The free macOS runner pool caps concurrency, so macOS shards queue; read
runtime from each job's own start and finish times, not the run's wall clock.

## OS scope markers

OS requirements use `pytest.mark.posix_only(reason="...")`, `windows_only`,
`macos_only` or `linux_only`, with exactly one nonempty reason and one scope
per test. A module-level `pytestmark` is read before import. Collection skips
with `<marker>: <reason>`; the `windows` smoke marker cannot accompany a scope
that excludes Windows. The tracked-source scanner refuses hand-written OS
`skipif`/`xfail` conditions and OS-guarded `pytest.skip`/`pytest.xfail`.
Root-user and missing-tool skips stay ordinary conditions.

The same scanner refuses a `/tmp` literal used as a real path: passed to
`dir=`, to `open`, `os` or `shutil` calls, or to path I/O such as
`Path("/tmp/x").write_text(...)`. Windows has no `/tmp`. Use
`shortest_temp_directory()` for socket or Postgres roots, the machine home's
tmp tree where the code under test writes runtime state, and pytest
`tmp_path` everywhere else. Data-only literals go on the allowlist in
`tests/test_os_scope_markers.py`.

Use these markers only when a test requires a native OS capability.

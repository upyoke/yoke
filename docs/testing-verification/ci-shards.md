# CI interpreter coverage and shard timing

CI executes the full suite on the newest supported Python endpoint. The oldest
endpoint runs in parallel on every CI event, pull requests included, covering
interpreter behavior while repository checks, documentation, generated files,
path snapshots, and installed wheel scenarios stay on the newest leg.

Full CI and change-scoped test selection default to Ubuntu 26.04
(`ubuntu-26.04`). The `YOKE_LINUX_RUNS_ON` override must select the same
supported substrate on self-hosted runners. Workflows use explicit releases;
never use the moving `ubuntu-latest` label. Server-image build and product
smoke jobs remain pinned to Ubuntu 24.04 until their own runner upgrade is
verified.

The shared `.github/actions/yoke-test-runner` action declares host prerequisites:
`postgresql-client-16` supplies the PostgreSQL 16 copy-lifetime tools. When
missing, GitHub-hosted runners install it from the PostgreSQL PGDG apt
repository; self-hosted runners refuse with `ci_runner_prerequisites_missing`
and the package list to install before retrying. The Docker PostgreSQL service
does not supply host clients. CI does not install embedded-engine libraries:
fresh Ubuntu 26.04 runners exercise the product's embedded PostgreSQL
portability. Runner upgrades require full CI on both supported Python endpoints.

The shared runner, full-CI contract job and selection plan install uv through
commit-pinned `astral-sh/setup-uv`, with its download/build cache enabled and
keyed on `uv.lock`. `uv sync --all-packages --locked` still creates each job's
own environment; no virtualenv is cached. Python setup does not cache pip.
Full-CI `test_shard` and `reuse_coverage` checkouts use `filter: blob:none`
with `fetch-depth: 0`: current files, all commits and tags remain available,
while historical blobs are fetched on demand. History is required by
setuptools-scm package versions, git-based tests and timing-profile lineage;
the container version job also retains full history.

After interpreter and uv setup, `ci_runner_prepare` overlaps the independent
host-prerequisite install, locked dependency sync and Docker Postgres startup.
It imports with `python3 -S` from the checkout before dependencies exist.
Every task has bounded commands and records its elapsed time; one barrier
joins all tasks before any later setup or pytest. A failure refuses as
`ci_runner_setup_failed`, names the task and recovery, and starts no tests.
The socket cleanup path is published before Docker starts, so the caller's
always-cleanup still removes resources on failure. Database readiness and
CREATEDB checks remain required after the barrier.

The full matrix uses sixteen shards per Python endpoint, with four xdist
workers on the measured hosted runners. `ci_shards.SHARD_COUNT` owns the
fan-out and selection cap; `.yoke/merge-queue.json` declares every required
shard context. Change these together and verify coverage before applying
the declaration to GitHub.

`runtime/ci_test_selection.py` owns the interpreter-independent selection. Its
collection hook applies the same scope in grouping, shards and coverage checks. Local and newest-interpreter runs retain all tests. Explicit
`ci_version_independent` markers can identify additional repository-only cases.

Every CI entry refreshes the timing weights from one successful retained run's
complete newest-interpreter report set. It shares that single profile artifact
with every shard for within-shard file ordering. In full CI, `reuse-coverage`
refreshes weights and runs repo contracts in parallel with the collection and
wheel build in `repo-contracts`. File assignment uses the committed profile,
so grouping never waits for retained-report downloads or repository checks.
Both prerequisite jobs must pass before shards start; required check names
and independent shard-coverage checks stay unchanged.
Missing report telemetry prints a named reason and recovery while CI retains
the committed profile; telemetry availability never decides whether tests run.
There is no scheduled refresh or automated source commit.
Automatic refresh only accepts runs whose source includes the commit that last
changed `.test_durations`. A newer run from an older branch cannot overwrite a
measured fixture-cost reset. This check needs Git history; unavailable source
revisions are ineligible. If no compatible complete run is retained, every
shard keeps using the committed baseline. An explicit `--reports` refresh names
the verified measurements used to establish a new baseline.
Before accepting a retained run, refresh validates its downloaded reports.
Incomplete, duplicate, failed, empty or malformed sets print
`ci_profile_run_skipped` with the run id and reason, then try the next eligible
run. Each run's reports stay separate; rejected reports never enter the chosen
profile. If every candidate is rejected, the committed profile stays intact.

To refresh the committed baseline in a claimed source lane:

```text
yoke dev run -- python3 -m yoke_core.tools.ci_durations_refresh --target-root <checkout> --latest --repository owner/repo --python 3.14
```

Commit the resulting `.test_durations`; use `--reports <download-directory>` to
read a previously downloaded complete report set from one successful run.
`--help` owns the options. The tool refuses incomplete, failed, empty, or
duplicate report sets before replacing the existing profile.

JUnit testcase times include parallel contention. Each report's weights are
scaled to its actual suite wall time before greedy file assignment.
Tests removed from the current checkout disappear from the refreshed profile.
Existing cases blend their prior weight equally with the new measurement;
this rolling average damps setup attribution and runner contention noise.
Use `--reset` with a complete passing report set after changing fixture setup
or scheduling costs substantially, so obsolete costs do not bias the baseline.
`ci_shard_groups` runs one collect-only pass without xdist in `repo-contracts`,
in parallel with portable-wheel construction, using committed weights. It
uses plain assertions and suppresses node-ID output to avoid execution-only
rewriting and terminal work. It records fixture and marker facts and publishes
`ci-shard-groups.json` for both interpreter scopes. It sums recorded durations per file, gives unmeasured files
the known mean file weight, and places the heaviest fixture units on the
lightest shard. Git's tracked-file order breaks equal-weight ties. Files using
product-wheel fixtures remain one indivisible unit. The grouping log records
collection/grouping elapsed seconds for comparison with saved shard timings.
When any collected test lacks a timing entry, grouping emits the GitHub warning
`ci_profile_missing_durations` once with the missing and total test counts.
Refresh `.test_durations` from a complete successful current-tree run to recover;
missing measurements never remove tests or prevent grouping.

Each shard downloads that exact artifact and writes its assigned root-relative
paths to `ci-shard-files.txt`. The existing `ci_selection_collect` plugin keeps
all three suite roots as conftest anchors and skips every unassigned file before
import. A worker collects only its assigned files; no post-collection split
runs. Empty, unreadable or invalid groups refuse as `ci_shard_groups_invalid`
with regeneration/download recovery. The uploaded shard artifact retains its
file list. pytest-split remains a dependency for change-scoped selection runs. Xdist uses `loadfile` so a file also stays on one
worker. This stabilizes setup attribution and avoids repeating a file's
fixtures across shards or workers. Local partial splitting keeps pytest-split's
ordinary individual-test behavior.
Files enter the worker queue in descending measured duration; xdist's default
test-count reorder is disabled so short, expensive files start early.
The **Check runner capacity** step runs `ci_shards check-runner-capacity`
before **Run pytest** and records CPU model, core count, and Python-loop timing. The probe takes the median of three local loops;
`ci_shards.MAX_PYTHON_LOOP_SECONDS` admits values up to 0.05 seconds. Above
that limit the shard exits non-zero before pytest with
`ci_runner_slow: runner refused before pytest` and the measured value and limit,
in both the job log and uploaded `pytest-output.txt`. Restore runner capacity;
no test verdict was produced. When only **Check runner capacity** failed,
item-owned [CI recovery](../public/github/index.md#failed-ci-job-recovery)
allows `rerun-failed` and sends `rerun-failed-jobs`, within the existing
three-attempt limit. A failed **Run pytest** or any other failed step still
refuses `ci_rerun_verdict`; fix the cause, commit and verify again.
This admission check does not change test selection. Missing CPU-model telemetry does not block tests.
The **Run pytest** step sets `PYTHONUNBUFFERED=1` so progress reaches the
streaming log without Python output buffering.

The cutoff uses retained logs from three runs on 2026-10-21:
[the sixteen-shard trial](https://github.com/upyoke/yoke/actions/runs/39642454534)
(32 probes), [the first stalled run](https://github.com/upyoke/yoke/actions/runs/39646102090)
(16 retained probes), and [the second stalled run](https://github.com/upyoke/yoke/actions/runs/39647919714)
(16 retained probes). The 62 healthy observations ranged from 0.00766 to
0.02254 seconds, with a 0.01699-second median:

| Python loop seconds | Healthy observations |
| --- | ---: |
| Below 0.010 | 7 |
| 0.010 to below 0.015 | 9 |
| 0.015 to below 0.020 | 30 |
| 0.020 to below 0.025 | 16 |

The two stalled hosts measured 0.08952 and 0.06776 seconds. The 0.05-second
limit is over twice the healthy maximum and below both degraded values;
none of these healthy observations trips it. The existing probe ran 3m18s
and 3m30s after those jobs started, so admission would have stopped them
there rather than letting pytest crawl to the 35-minute cap. Setup still
precedes this probe; this check does not bound setup time or detect a host
that degrades after admission.

GitHub-sync test databases clone the existing per-worker production schema
template rather than replaying schema DDL for every case; their project and
actor seeds and connection-close isolation remain per case.

Full CI builds portable product wheels once in `repo-contracts`, using its
already prepared build interpreter. Selection CI builds them
in its plan job and includes them beside the shared timing profile in the
existing `ci-test-durations` artifact. The product directory contains exactly the four
`py3-none-any` product wheels plus a manifest with the actual checkout commit,
tree and wheel hashes. A PR's synthetic merge commit is the artifact identity.
Each job verifies that identity before copying products into its own wheelhouse;
a different commit is refused even if its tree matches. Third-party wheels
are resolved separately for each job's interpreter and platform, and the
core-only clean installation proof still runs. No virtualenv crosses jobs.

`YOKE_CI_PRODUCT_WHEELS` selects the downloaded artifact. Missing, altered or
incompatible artifacts refuse as `ci_product_wheels_invalid` and name the
rebuild/download recovery; an explicit artifact never silently falls back to
a local build. Without this variable, local tests retain their existing
locked, per-run build. Repository contracts and portable-wheel construction
remain required on reused trees; pytest and its per-job installations are skipped.

Every file that uses `product_venv` or `product_wheelhouse` is scheduled as
one unit, so a single shard pays the product installation. Wheel smokes share
one session virtual environment, synchronized across xdist
workers with a file lock. The fixture proves the core-only dependency closure
before installing the client, and creates its completion sentinel last.
Each scenario retains its own checkout, machine configuration, environment,
and subprocess substitutes; scenarios never modify shared site-packages.
The core-free scenario disables site loading and uses a filtered view of those
installed packages on the same interpreter, retaining its engine-absence proof.
The eight import-graph scenarios remain eight parametrized cases in
`tests/import_graph/test_yoke_cli_wheel_smoke.py`.

## Prove shard coverage

The required `shard-coverage (3.11)` and `shard-coverage (3.14)` jobs run
once all shards finish, including when a shard failed. Each downloads every
`pytest-output-<python>-<shard>` report and independently collects the full
suite without splitting or xdist. The older interpreter's collection applies
its normal repository-only deselection. A skipped testcase still counts as
one execution; a deselected testcase is outside that interpreter's contract.

`ci_shard_coverage` compares JUnit identities against that collection and
refuses missing, duplicated or unexpected tests with their names and Python
version. A missing report refuses `ci_shard_reports_missing` and names its
shard. Restore the report upload or fix collection/profile divergence, then
verify the corrected commit. `shard-collection-<python>` retains the expected
IDs and collection log. To replay saved evidence:

```text
yoke dev run -- python3 -m yoke_core.tools.ci_shard_coverage --python 3.14 --reports REPORT_DIRECTORY --expected expected-tests.json
```

On `SUITE_ALREADY_PROVEN`, both coverage jobs skip collection and report
comparison and remain successful, as the test shards do. Required check names
live in `.yoke/merge-queue.json`; apply that declaration when changing them.

Each shard records every worker's assigned collection count and sorted-ID
SHA-256 in `pytest-output.txt`. Compare these with `ci-shard-files.txt` and
the published grouping facts when diagnosing collection. Stable parameter IDs
across runner patch versions keep profile weights and the independent coverage
comparison meaningful. Group assignment is computed once and shared; workers
never recompute it from their own collection.

## Reproduce a timing comparison

Save the completed run object from GitHub's
[workflow run REST endpoint](https://docs.github.com/en/rest/actions/workflow-runs#get-a-workflow-run)
as `RUN.json`. Save the complete `jobs` array and pagination envelope from the
[workflow jobs REST endpoint](https://docs.github.com/en/rest/actions/workflow-jobs#list-jobs-for-a-workflow-run)
as `JOBS.json`; include every page. Download `pytest-output-*` and
`yoke-ci-coverage-*` artifacts from that same run. Then execute:

```text
yoke dev run -- python3 runtime/api/tools/ci_timing_report.py --run RUN.json --jobs JOBS.json --coverage COVERAGE.json --reports REPORT_DIRECTORY --output REPORT.json
```

The report refuses active, failed, mismatched, incomplete or duplicate evidence.
It records actual checkout identity, endpoint pass/skip counts, each job's
queue/setup/test/total seconds, observed concurrent jobs, CPU telemetry and
slowest cases/files. Workflow elapsed time runs from creation through the last
job completion. Runner-minute totals exclude queue time; the rounded estimate
is consumption, not a billing invoice. A reused run has no new coverage artifact
or complete JUnit set and cannot be represented as an executed full observation.

## Measured fan-out tradeoff

A matched-profile trial on 2026-10-21 measured the optimized fixture and wheel
layout on both Python endpoints. Every run executed all required cases;
the eight- and sixteen-shard trials each reported 47,694 cases on Python 3.11
and 49,468 on Python 3.14, with 94 skips per endpoint.

| Configuration | Workflow elapsed | Runner minutes | Peak concurrent jobs |
| --- | ---: | ---: | ---: |
| [Eight shards](https://github.com/upyoke/yoke/actions/runs/39640036607) | 14m32s | 173.98 | 17 |
| [Sixteen shards](https://github.com/upyoke/yoke/actions/runs/39642454534) | 10m43s | 237.45 | 34 |

Sixteen shards shortened elapsed time by 26% while increasing runner consumption
by 36%. Shard queue delays were 2–3 seconds and 3–5 seconds respectively, so
runner availability did not force two waves. Both used four-CPU hosted runners,
with varying AMD EPYC models; this is an observed comparison, not a guaranteed
runtime. The eight-minute target was not reached by this trial. Refresh weights
from the chosen layout because per-worker setup and whole-file allocation change
when the matrix grows; preserve genuine boot, migration and restore work.

Runner consumption remains a cost measure even where GitHub's public-repository
standard-runner policy makes compute free. Do not infer invoice charges or an
account concurrency limit from these measurements. Repeat the report after
material fixture or scheduling changes, using naturally triggered full runs.

## Change-scoped selections

`yoke-tests-selection.yml` runs a change-scoped selection with the same
layout as a `test-shard` job on the newest Python. Both jobs prepare their
runner through the composite action `.github/actions/yoke-test-runner`. A
composite action keeps each job's own check names, so the required
`test-shard (...)` contexts in `.yoke/merge-queue.json` stay unchanged. The
selection's plan job refreshes the timing profile from retained CI reports
and shares it as `ci-test-durations`, as full CI's `reuse-coverage` does.
Selection sizing and splitting both use that refreshed profile. Selection
shards set `YOKE_CI_PYTHON_SCOPE=all`, so whole files stay on one shard.

A selection shard passes pytest the same three roots as a full shard. It
loads `yoke_core.tools.ci_selection_collect`, which skips every file outside
the selection before importing it, so collection never takes longer than full
CI's. Explicit dispatched paths without a merge base run exactly as named.

`yoke_core.tools.ci_shard_sizing.selection_estimate` sizes a selection
against the whole profile. It earns one shard per 60 profiled seconds, up
to 16. It is full CI's work at 50% or more of the suite's profiled seconds
(`FULL_CI_SHARE`). The dispatcher refuses that work before pushing. The plan
job refuses it before any shard starts, and the dispatcher reports that run
as the same named refusal, not a test failure. Each names the full QA case
command. A dispatched path outside every root is also named to pytest, so
it still runs. Raise `FULL_CI_SHARE` only with measured selection and full CI
durations recorded on the item that changes it.

## Identical-tree coverage reuse

When `reuse-coverage` decides a run must execute the suite, it publishes a
one-day artifact named `yoke-ci-coverage-<tree>`. Its `yoke-ci-coverage.json`
names the commit and tree the shards actually check out, the run and attempt,
and the per-interpreter scope and shard count the matrix executes. A pull
request run tests GitHub's synthetic merge commit, not the pull request head,
so the evidence records that checkout. The coverage counts as completed only
once that attempt concludes `success`.

Every run's `reuse-coverage` job
(`packages/yoke-core/src/yoke_core/tools/yoke_ci_tree_reuse.py`) looks up
evidence for its own checked-out tree. It reuses evidence only when the
artifact is unexpired and under 24 hours old, comes from a same-repository
`yoke-ci.yml` run whose recorded attempt concluded `success`, and names the
same tree and the complete required coverage. A merge-queue entry that adds
one pull request to an unchanged base therefore reuses that pull request's
run, and the push after landing reuses its queue run. A moved base or a
multi-entry queue composition creates a new tree and runs the suite.

On reuse, the test shards skip setup and pytest but still report every
required context. Repository contracts, browser runtime, the container build,
release artifacts, and attestations always run. A reusing run publishes no
evidence, so a reuse always names an original executed proof whose age cannot
be renewed. The job summary lists the covering run URL, or every rejected
artifact with its reason; any rejection or probe fault runs the suite, which
needs no recovery step.

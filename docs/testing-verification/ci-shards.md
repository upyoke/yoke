# CI interpreter coverage and shard timing

CI executes the full suite on the newest supported Python endpoint. The oldest
endpoint runs in parallel on every CI event, pull requests included, covering
interpreter behavior while repository checks, documentation, generated files,
path snapshots, and installed wheel scenarios stay on the newest leg.

`runtime/ci_test_selection.py` owns the interpreter-independent selection. Its
collection hook runs before pytest-split, so every selected test belongs to
exactly one shard. Local and newest-interpreter runs retain all tests. Explicit
`ci_version_independent` markers can identify additional repository-only cases.

Every CI entry refreshes the timing weights from one successful retained run's
complete newest-interpreter report set. It shares that single profile artifact
with every shard, so matrix jobs cannot select against different profiles.
Missing report telemetry prints a named reason and recovery while CI retains
the committed profile; telemetry availability never decides whether tests run.
There is no scheduled refresh or automated source commit.
Automatic refresh only accepts runs whose source includes the commit that last
changed `.test_durations`. A newer run from an older branch cannot overwrite a
measured fixture-cost reset. This check needs Git history; unavailable source
revisions are ineligible. If no compatible complete run is retained, every
shard keeps using the committed baseline. An explicit `--reports` refresh names
the verified measurements used to establish a new baseline.

To refresh the committed baseline in a claimed source lane:

```text
yoke dev run -- python3 -m yoke_core.tools.ci_durations_refresh --target-root <checkout> --latest --repository owner/repo --python 3.14
```

Commit the resulting `.test_durations`; use `--reports <download-directory>` to
read a previously downloaded complete report set from one successful run.
`--help` owns the options. The tool refuses incomplete, failed, empty, or
duplicate report sets before replacing the existing profile.

JUnit testcase times include parallel contention. Each report's weights are
scaled to its actual suite wall time before pytest-split's greedy assignment.
Tests removed from the current checkout disappear from the refreshed profile.
Existing cases blend their prior weight equally with the new measurement;
this rolling average damps setup attribution and runner contention noise.
Use `--reset` with a complete passing report set after changing fixture setup
or scheduling costs substantially, so obsolete costs do not bias the baseline.
CI aggregates those weights by file and assigns whole files through the same
least-duration algorithm. Xdist uses `loadfile` so a file also stays on one
worker. This stabilizes setup attribution and avoids repeating a file's
fixtures across shards or workers. Local partial splitting keeps pytest-split's
ordinary individual-test behavior.
Files enter the worker queue in descending measured duration; xdist's default
test-count reorder is disabled so short, expensive files start early.
Each shard log records CPU model, core count, and a short Python-loop timing
for diagnosing runner variation. This telemetry never changes test selection.
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

Wheel smokes share one session virtual environment, synchronized across xdist
workers with a file lock. The fixture proves the core-only dependency closure
before installing the client, and creates its completion sentinel last.
Each scenario retains its own checkout, machine configuration, environment,
and subprocess substitutes; scenarios never modify shared site-packages.
The core-free scenario disables site loading and uses a filtered view of those
installed packages on the same interpreter, retaining its engine-absence proof.
The eight import-graph scenarios remain eight parametrized cases in
`tests/import_graph/test_yoke_cli_wheel_smoke.py`.

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

## Change-scoped selections

`yoke-tests-selection.yml` runs a change-scoped selection with the same
layout as a `test-shard` job on the newest Python. Both jobs prepare their
runner through the composite action `.github/actions/yoke-test-runner`. A
composite action keeps each job's own check names, so the required
`test-shard (...)` contexts in `.yoke/merge-queue.json` stay unchanged. The
selection's plan job refreshes the timing profile from retained CI reports
and shares it as `ci-test-durations`, as `repo-contracts` does. Selection
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

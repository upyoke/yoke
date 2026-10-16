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

Wheel smokes share one session virtual environment, synchronized across xdist
workers with a file lock. The fixture proves the core-only dependency closure
before installing the client, and creates its completion sentinel last.
Each scenario retains its own checkout, machine configuration, environment,
and subprocess substitutes; scenarios never modify shared site-packages.
The core-free scenario disables site loading and uses a filtered view of those
installed packages on the same interpreter, retaining its engine-absence proof.
The eight import-graph scenarios remain eight parametrized cases in
`tests/import_graph/test_yoke_cli_wheel_smoke.py`.

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

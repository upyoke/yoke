# Full-suite authority: CI

How local verification is scoped, why the gate run is the one full
execution for a tree, and how to read a selection that widened.
Companion to [`docs/testing-verification.md`](../testing-verification.md).

The full three-anchor suite runs off-machine in CI on both the pull request
and the merged commit on `main` (`.github/workflows/yoke-ci.yml` triggers on
`pull_request` and `push` to `main`). The protected merge path requires the
PR checks, so every merge carries one complete pre-merge sweep, and the push
trigger re-proves the true merge commit afterward. Local verification stays
change-scoped:

- **While implementing** — run the impacted selection over the branch diff:

  ```bash
  yoke watch pytest --impacted main --bounded
  ```

  Selection is reverse-import reachability, hardened two ways: dotted
  module paths appearing as string literals (subprocess `-m` targets,
  patch targets, registry keys) count as dependency edges, and a small
  always-run floor of fast cross-cutting contract tests executes on every
  selection. The conservative full-sweep fallback (non-Python changes,
  conftest or shared-fixture edits, test tooling) still catches anything
  reachability cannot bound.
- **At the review gate** — the project-default quick plan runs the same
  impacted selection and blocks the transition when a selected test fails.
- **At done** — no local sweep. The merge already required green PR checks,
  and the pushed merge commit gets its own CI run.

## One full execution, not two

Iterate as much as you want with the cheap layers — a single failing test,
the changed module's paths, `yoke watch pytest --impacted main --bounded`.
Those are the recommended loop, and running impacted selection repeatedly
while fixing is exactly what it is for.

`--bounded` changes only what happens when selection comes back
*unbounded*. Plain `--impacted` answers an unbounded change with the full
sweep, which is right when nothing runs after you. With `--bounded` the
selector declines to widen: it prints
`selection unbounded (<rule>: <paths>) — deferring full coverage to the
final QA gate` and runs the subset reachability could still compute. Mid
iteration that verdict means *keep testing what you judge relevant* — the
gate run covers the rest. The verdict itself is never suppressed.

What must not happen twice on one tree is the **full** run. The review
gate re-executes the identical registered command, and that execution is
the one that produces the recorded verdict — so proving the same tree by
hand first is pure duplicate compute. Both invocations also sit in the
shared cluster's admission queue, so a fleet of sessions each doubling up
multiplies the wait for everyone: one observed session paid 8m16s and
21,371 tests twice for a single tree. Let `yoke qa case run` be the run
that closes the loop.

That run is watchable rather than opaque, which is what made the
hand-run-first habit tempting. The case runner streams the command's
output live to stderr as it arrives and names its raw capture file before
the command starts, so following a long gate run needs no second copy of
it; on completion it restates the verdict, exit code, and capture path on
stderr while stdout stays machine-readable JSON.

Re-running a case after the tree changes is a different execution, not a
duplicate: fix-then-rerun and the post-rebase merge-time run both stay
required.

## Why a selection widened

Every `--impacted` run writes one structured line into its captures
alongside the prose reason:

```text
watch_pytest impacted-selection scope=full_sweep rule=shared_test_fixture triggers=runtime/api/conftest.py tests=0
```

`scope` is `impacted`, `full_sweep`, or `bounded_deferral`. `rule` is one
of `FALLBACK_RULES` — `shared_test_fixture`, `test_tooling_module`,
`unmapped_file_kind`, `no_importable_module` — and `triggers` names the
exact changed files that fired it. The identifiers are stable because
they are the grouping key: sweeping a period of run captures for
`impacted-selection ` answers whether widening is legitimate core churn
or a file kind reachability never modelled. A docs- or skills-only edit
widening to 21,000 tests is the second kind. Tune the selector against
what that data indicts rather than against intuition — a rule that fires
constantly on genuinely central files is working correctly.

## When CI disagrees with the local run

Impacted selection makes a falsifiable claim: *this change cannot affect
that test*. Every CI failure gets triaged against that claim before
anything else:

- **The failing test was not in the local selection** — the reachability
  model missed a dependency edge. That is a selector defect, never noise.
  Root-cause the coupling the import graph could not see (the residual
  blind spots for `.py`-only changes are non-import coupling: subprocess
  module invocations, string-target patching, runtime string dispatch),
  then extend the index modeling or the trigger set that composes
  `FULL_SWEEP_TRIGGERS` — `SHARED_TEST_FIXTURE_PATHS` for pytest
  infrastructure, `TEST_TOOLING_PATHS` for the selection and run
  machinery — **and add a regression test to the selector's own tests in
  the same fix**. The selector only stays trustworthy if every
  counterexample tightens it.
- **The failing test was selected and passed locally** — an environment
  difference, not a selection miss: CI runs Python 3.10 and 3.13 shards
  on Linux while local runs one interpreter on macOS, plus concurrency,
  ordering, and neighbor-merge interactions. No local selection can catch
  this class; it is exactly why CI is the authority.

## Red-main protocol

A failing `push`-to-`main` CI run means a merge landed broken despite green
PR checks (a semantic conflict with a neighboring merge, or a selection
miss per the triage above). Whoever merged the commit that turned main red
owns the response: revert or fix forward immediately, before merging
anything else on top — and when the triage says selection miss, the
selector fix ships with it. Treat the failing run's first red shard as
that work's evidence, not a background alarm.

## CI-outage fallback

When CI is unreachable, the local full gate returns as the documented
exception:

```bash
yoke watch pytest -- runtime/api/ runtime/harness/ tests/
```

Record in the verification evidence that the local sweep substituted for CI
and which commit it covered. Never merge with neither proof.


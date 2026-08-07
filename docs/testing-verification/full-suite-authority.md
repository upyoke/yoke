# Full-suite authority: CI

How local verification is scoped, why the gate run is the one full
execution for a tree, and how to read a selection that widened.
Companion to [`docs/testing-verification.md`](../testing-verification.md).

The full three-anchor suite runs off-machine in CI on both the pull request
and the merged commit on `main` (`.github/workflows/yoke-ci.yml` triggers on
`pull_request` and `push` to `main`). Branch protection on main requires only
`signature-check` (CLA); Yoke-owned gates — the QA CI run conclusion and the
merge engine's all-check-runs poll — authorize the suite. Local verification
stays change-scoped:

- **While implementing** — run the impacted selection over the branch diff:

  ```bash
  yoke watch pytest --impacted main --bounded
  ```

  Selection is reverse-import reachability, hardened two ways: dotted
  module paths appearing as string literals (subprocess `-m` targets,
  patch targets, registry keys) count as dependency edges, and a small
  always-run floor of fast cross-cutting contract tests executes on every
  selection (CLI registry, operation inventory, adapter parity, and Atlas
  currency). The conservative full-sweep fallback (non-Python changes,
  conftest or shared-fixture edits, test tooling) still catches anything
  reachability cannot bound.
- **At the review gate** — the project-default plan case blocks the
  transition when verification fails. Because this project declares a
  `ci_workflow_file` capability, that case registers on the `command-ci`
  method and the gate executes on CI rather than on the machine (see
  *The gate runs on CI* below).
- **At done** — no local sweep. The merge path already waited on green
  check-runs (PR merges) or ran the local merge after the gate (standalone),
  and the pushed merge commit gets its own CI run.

## The gate runs on CI

A project that declares its required-status-check workflow gets its
`quick` and `full` registered scopes bound to the `command-ci` method
(`ci_run` executor). `yoke qa case run --requirement-id <id>` then:

1. pushes the item's lane branch to `origin` — item branches otherwise
   stay local until merge, so the gate has to publish before it can run;
2. dispatches the declared workflow against that branch with a
   correlation id, reusing the deployment layer's dispatch machinery so a
   lost dispatch response is recovered by its GitHub-visible marker
   instead of reposted;
3. waits for the run and records its conclusion as the verdict, with the
   run URL and the exact head sha as evidence.

Why: the local machine runs one heavy gate at a time behind the
admission slot, where the suite has been measured at 35–55 minutes under
fleet contention; CI runs the same suite across four duration-balanced
shards with disposable Postgres containers and freshly provisioned
capacity, and then re-runs it post-merge regardless. Two items gating at
once both route to CI and run there in parallel — the admission slot is a
local-machine resource and never serializes CI runs.

`worktree_run` stays the local executor for the same Command method and
remains the fallback for offline or local-only operation. Choosing it is
a plan-case decision, not a silent runtime downgrade: a CI case whose
workflow cannot be reached fails with a named reason rather than quietly
running the suite on the machine the routing exists to keep free.
Deployed-environment scopes (`e2e`, `smoke`) are never routed — they
assert against a running site behind a base URL CI has no access to.

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
watch_pytest impacted-selection scope=full_sweep rule=shared_test_fixture triggers=runtime/api/conftest.py files=2300 of 2300 items=unknown of unknown
```

`scope` is `impacted`, `full_sweep`, or `bounded_deferral`. `rule` is one
of `FALLBACK_RULES` — `shared_test_fixture`, `test_tooling_module`,
`unmapped_file_kind`, `no_importable_module`,
`effectively_full_selection` — and `triggers` names the
exact changed files that fired it. The identifiers are stable because
they are the grouping key: sweeping a period of run captures for
`impacted-selection ` answers whether widening is legitimate core churn
or a file kind reachability never modelled. A docs- or skills-only edit
widening to 21,000 tests is the second kind. Tune the selector against
what that data indicts rather than against intuition — a rule that fires
constantly on genuinely central files is working correctly.

`files=N of M` always counts pytest file paths, never collected test items.
The pre-run line reports `items=unknown of unknown` when collection data is
not yet available. Before the watcher exit sentinel, its selection summary
repeats both units and fills in the collected item count; a full sweep can
also report that value as the item denominator, while a partial selection
keeps the unavailable universe total explicit as `of unknown`.

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

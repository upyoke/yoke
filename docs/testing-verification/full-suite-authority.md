# Full-suite authority: CI

How local verification is scoped, why the gate run is the one full
execution for a tree, and how to read a selection that widened.
Companion to [`docs/testing-verification.md`](../testing-verification.md).

The full three-anchor suite runs off-machine in CI on both the pull request
and the merged commit on `main` (`.github/workflows/yoke-ci.yml` triggers on
`pull_request` and `push` to `main`). A main-push run may short-circuit when
`reuse-coverage` finds a recent successful dispatch/push yoke-ci run whose
head commit shares HEAD's tree object id (fail-open otherwise; merge commits
that rewrite the tree still run the matrix). Branch protection on main
requires only `signature-check` (CLA); Yoke-owned gates — the QA CI run
conclusion and the merge engine's all-check-runs poll — authorize the suite.
Local verification stays change-scoped:

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
(`ci_run` runner). `yoke qa case run --requirement-id <id>` then:

1. pushes the item's lane branch to `origin` — item branches otherwise
   stay local until merge, so the gate has to publish before it can run;
2. dispatches the declared workflow against that branch with a
   correlation id, reusing the deployment layer's dispatch machinery so a
   lost dispatch response is recovered by its GitHub-visible marker
   instead of reposted;
3. waits for the run and records its conclusion as the verdict, with the
   run URL and the exact head sha as evidence.

A `pull_request` run that reached a verdict on that exact commit —
`success` or `failure` — is reused instead of step 2, because it already
proved the same tree. A run that stopped short of one (`cancelled`,
`timed_out`, `startup_failure`) proved nothing and is not evidence: the
gate dispatches instead, which is what lets the same commit reach green
after a run was cancelled. Reusing it would wedge the gate there, because
every retry finds that same completed run at that same head sha.

The CI budget is wall clock spanning the push, the pull request, the
Actions queue, and the suite — not execution alone the way a local
`worktree_run` command's is. Both registered scopes therefore take the
CI runner's own budget when it is the wider one, so a healthy run that
queues behind congested Actions is never reaped as infrastructure
trouble.

## Queue projects verify pull-request-first

Reuse by luck is worth little: GitHub's required checks take the latest
check run per name, so a dispatch green never satisfies queue entry, and
the entry run GitHub mints when the landing pull request opens re-proves
the same tree the dispatch just proved. Ordering fixes it. For a project
declaring the `merge_queue` capability, the gate runs steps 1-3 as:

1. **rebase** the lane onto `origin/<default branch>`, after the merge
   engine's own safety-stash gate has classified any uncommitted work.
   This is the only free moment to rebase — no gate evidence exists yet,
   so nothing is invalidated — and it makes the entry-run tree
   approximately the tree the queue's train will build;
2. **push**, then **open the landing pull request** (or converge on the
   one already open) through the same `ensure_landing_pull_request` the
   landing itself uses, so the landing enqueues this pull request rather
   than opening a second;
3. **wait for the pull-request entry run** and record its conclusion as
   the verdict. Dispatch stays the fallback for a commit that produced no
   entry run, a run whose head sha does not match, and a run that
   concluded without a verdict — an entry run cancelled by the workflow's
   concurrency group when the next push superseded it, for instance.

The merge queue's `merge_group` train run then applies the same tree-oid
reuse probe as a main push: a solo item rebased onto the base builds a
candidate tree byte-identical to its entry tree, so the train self-skips
and reports through the coverage receipt. A batch, or a train built after
the base moved, is a tree no single run covered and runs the full suite —
which is exactly when the integration proof is real.

The floor this reaches: a solo item costs one suite end to end; a batch of
N costs N entry suites plus one shared train.

Two honest trades. The pull request becomes visible on GitHub during
review and polish rather than at merge, and a polish-phase push
re-triggers entry CI — which it would have re-gated anyway.

Why: the local machine runs one heavy gate at a time behind the
admission slot, where the suite has been measured at 35–55 minutes under
fleet contention; CI runs the same suite across four duration-balanced
shards with disposable Postgres containers and freshly provisioned
capacity, and then re-runs it post-merge unless same-tree reuse applies.
Two items gating at once both route to CI and run there in parallel —
the admission slot is a local-machine resource and never serializes CI
runs.

`worktree_run` stays the local runner for the same Command method and
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

# Full-suite authority: CI

CI owns full-suite evidence; local execution stays targeted. Read the
[source-dev doctrine](../source-dev-doctrine.md) for candidate-source wrappers
and [verification rules](../public/reference/agent-rules/verification.md)
before selecting or re-entering a run. This source reference owns the CI
adoption, queue and reachability mechanics.

The full suite — the project's Project Structure `test_roots` attachments,
not a yoke-only path triple — runs off-machine in CI on both the pull request
and the merged commit on `main` (`.github/workflows/yoke-ci.yml` triggers on
`pull_request` and `push` to `main`). A main-push run may short-circuit when
`reuse-coverage` finds a recent successful dispatch/push yoke-ci run whose
head commit shares HEAD's tree object id (fail-open otherwise; merge commits
that rewrite the tree still run the matrix). Branch protection on main
requires upstream's `signature-check` (CLA) only in `upyoke/yoke`; the doctor reads the project GitHub binding before expecting it. Yoke-owned gates — the QA CI run
conclusion and the merge engine's all-check-runs poll — authorize the suite.
Local verification stays change-scoped:

- **While implementing** — run the impacted selection over the branch diff:

  ```bash
  yoke watch pytest --impacted main --bounded
  ```

  That selection executes on CI, not on this machine. Yoke declares a
  `ci_workflow_file` capability, so the wrapper and the generic runner
  behind it push the lane commit, dispatch
  `.github/workflows/yoke-tests-selection.yml` against it with the merge
  base the change is measured against, stream the run, and adopt its
  conclusion (0 success, 1 failure, 2 refused before dispatch, 3 timed
  out, 4 CI unreachable or dispatch refused, 5 cancelled). The CI job
  computes the identical selection from the same code, so its
  `impacted-selection` telemetry line matches what this machine would
  have printed. A remote dispatch is correlated by a request id derived
  from the head commit and the arguments, so re-running the same
  selection on the same commit rejoins the run already in flight rather
  than paying for a second one.

  A large selection runs on several runners at once: a plan job sizes it
  against the committed duration profile using one spelling of each path
  and publishes the matrix and split count, so shards cover it once and a
  failed shard is the run's verdict. Small selections plan one shard;
  each uploads `pytest-output-selection-N`. Selection CI installs the
  same Node/tsc toolchain as full CI.

  It refuses rather than testing the wrong tree: an uncommitted tree (CI
  tests the pushed commit), and a checkout sitting on the base branch
  instead of a lane. It drops `-n`/`--numprocesses`/`--rootdir`, which
  describe this machine, and names the drop.

  A selection workflow only becomes dispatchable once it is on the
  repository's default branch: GitHub registers `workflow_dispatch`
  workflows from that branch alone, so while the file exists only on the
  branch that adds it, the dispatch API answers 404 whatever ref is
  requested and the wrapper reports CI as unreachable. Routing therefore
  begins working on the merge that lands the workflow, not on the branch
  that authors it — until then, verify with `--local`.

  `--local` — or `YOKE_PYTEST_LOCAL=1` for a whole shell — is only a
  small targeted check expected to finish in about one minute for the
  entire invocation (one file or a small test count does not prove a
  fast runtime). Uncommitted work does not justify a slow local run.
  If a local check exceeds that, interrupt it cleanly, keep the
  capture as incomplete, commit, and run the selection on CI; do not
  repeat or background the slow local selection. Keep `--local` for
  order-sensitive `-n 0` debugging, machine-specific diagnostics, an
  unreachable CI, and projects that declare no CI workflow. Local runs
  take their xdist workers from one machine-wide budget rather than each
  claiming the machine (see below).

  Reverse-import selection follows dotted module strings, single-file paths,
  aliases/re-export chains, requested conftest/plugin fixtures and scoped
  autouse/hooks, plus registered handler function-id references. Bounded runs
  follow fixture/handler edges within three import hops. Changed tests always
  remain selected; bounded deferral cannot drop them for the contract floor.

  The always-run floor covers CLI/operation/adapter/Atlas and artifact parity,
  fresh-universe birth from the published wheel, and product-wheel installation
  smoke for CLI changes. Pack edits select catalog/prerequisite and installed
  Python/Node structured-events contracts. Non-Python/tooling changes or an
  unloadable registry can make selection unbounded; retain that verdict and
  judge the relevant remaining checks rather than claiming full coverage.
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

Before step 2 the gate asks GitHub what has already happened to that
exact commit, and the answer picks one of three paths. A run that reached
a verdict there — `success` or `failure` — is **adopted**: its conclusion
is the verdict and no CI capacity is spent. A run still in flight there is
**attached** to and polled, so a second invocation joins the first run
instead of racing a duplicate. Only an unexamined commit is
**dispatched**. Which path ran is recorded as `ci_run_source` in the run's
evidence and printed on the `# qa case run:` outcome line, so an adopted
verdict never reads like one this invocation paid for.

Matching is exact-sha: another commit is not this candidate's evidence.
Queue projects additionally require their pull-request entry run.

A run that stopped short of a verdict (`cancelled`, `timed_out`,
`startup_failure`) proved nothing and is not adopted: the gate dispatches
instead, which is what lets the same commit reach green after a run was
cancelled. Adopting it would wedge the gate there, because every retry
finds that same completed run at that same head sha.

**Recover a killed watcher through the same gate command.** A capture ending
`interrupted by signal 15` is incomplete and records no verdict; GitHub's run
continues. On the same commit, `yoke qa case run` adopts its settled conclusion
or rejoins it while running. Silence alone does not establish run state.

**A stopped turn is woken with the verdict rather than left to notice
it.** Every CI dispatch — the QA case gate and `yoke watch pytest`'s
remote selection alike — records the run (`session_ci_wait.record`). A
watcher that receives success or failure marks that wait notified
(`session_ci_wait.resolve`) so the sweep does not repeat it; a watcher
that dies first leaves the wait pending. Once the watching turn has
ended, `yoke_core.domain.session_ci_wait_observer` reads the conclusion
on the relay cadence and pushes one message carrying the verdict, the
run URL, the commit, and the continue command; an in-flight turn is left
alone because it is reading the run itself. The re-run above is what a
woken session does *with* the verdict. The notice rides the ordinary
session-message path and reaches every harness the same way.

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
3. **wait for the pull-request entry run to appear**, then adopt or
   attach to it exactly as above and record its conclusion as the verdict.
   Dispatch stays the fallback for a commit that produced no entry run, a
   run whose head sha does not match, and a run that concluded without a
   verdict — an entry run cancelled by the workflow's concurrency group
   when the next push superseded it, for instance.

The merge queue's `merge_group` train run then applies the same tree-oid
reuse probe as a main push: a solo item rebased onto the base builds a
candidate tree byte-identical to its entry tree, so the train self-skips
and reports through the coverage receipt. A batch, or a train built after
the base moved, is a tree no single run covered and runs the full suite —
which is exactly when the integration proof is real.

Landing then waits through the server's durable queue record only while that
wait can still produce a merge. Each live wait invokes the registered observer
once per minute; the server admits at most one project-wide GitHub sweep per
cadence, so a machine-relay outage cannot stop record refresh and extra lanes
do not multiply the reads. The record retains the named `queue_holding`,
`queue_entry_state`, and `merge_when_ready` outcomes with its refresh and
semantic-change times. A missed cadence refuses as `landing_record_stale`
instead of falling back to worker-local GitHub or git polling. If the pull
request's required checks have already concluded red and nothing is in flight
for that head sha, the record observer disarms merge-when-ready so a later green
cannot auto-merge without the gate recording a new verdict, and `yoke merge
item --wait` returns that terminal failure immediately instead of spending the
wait budget.

A solo same-tree landing can reuse its entry proof; a batch or changed base
needs the combined train proof. The pull request is visible during review and
polish, and a later polish push requires fresh entry evidence. CI runs
independently across duration-balanced shards and Python versions owned by
`yoke_core.tools.ci_shards`; the local admission slot does not serialize it.

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

The registered QA gate is the one full execution per tree. A hand-run full
sweep beforehand duplicates its work without replacing the native verdict.
Use the targeted iteration layers above, then `yoke qa case run`.

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
watch_pytest impacted-selection scope=full_sweep rule=test_tooling_module triggers=packages/yoke-core/src/yoke_core/tools/run_tests.py files=2300 of 2300 items=unknown of unknown
```

`scope` is `impacted`, `full_sweep`, or `bounded_deferral`. `rule` is one
of `FALLBACK_RULES` — `test_tooling_module`, `unmapped_file_kind`,
`no_importable_module`, `effectively_full_selection`,
`dispatch_registry_unloadable` — and `triggers` names the
exact changed files that fired it. Stable rule and trigger identifiers let capture analysis distinguish real
central-code widening from missing reachability. Mixed docs/Python changes
retain the Python remainder; one near-total path does not erase reachability
from other changed paths. Use that evidence when extending the selector.

`files=N of M` always counts pytest file paths, never collected test items.
The pre-run line reports `items=unknown of unknown` when collection data is
not yet available. Before the watcher exit sentinel, its selection summary
repeats both units and fills in the collected item count; a full sweep can
also report that value as the item denominator, while a partial selection
keeps the unavailable universe total explicit as `of unknown`.

A bounded selection can also widen without becoming a full sweep when a
contract floor adds tests that import reachability cannot discover. Those
lines append `widening=<rule>:<path>` tokens. A `*` path means every change
activates that floor; a concrete path identifies the source mapping that
added its companion tests. For example,
`widening=repo_cleanliness_contract:*` explains why the live-tree retired-term
scan runs for an otherwise unrelated tracked-content change.

## When CI disagrees with the local run

Impacted selection makes a falsifiable claim: *this change cannot affect
that test*. Every CI failure gets triaged against that claim before
anything else:

- **The failing test was not in the local selection** — the reachability
  model missed a dependency edge — unless `scope=bounded_deferral`, which
  truncates correct edges and drops tests above a broadly imported module.
  Otherwise it is a selector defect, never noise: root-cause the coupling
  the import graph could not see (non-import coupling — subprocess module
  invocations, string-target patching, an unmodelled dispatch or fixture
  shape), then extend the index modeling — conftest fixture use and
  function-id dispatch are modelled edges — or `TEST_TOOLING_PATHS`, the
  unbounded selection and run machinery, **and add a regression test to the
  selector's own tests in the same fix**.
  The selector only stays trustworthy if every counterexample tightens it.
- **The failing test was selected and passed locally** — an environment
  difference, not a selection miss: CI runs its declared Python-version matrix
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

# Testing and Verification

QA uses test plans, methods, capabilities, and readable outcomes. Requirements, runs, and artifacts remain execution records created by Yoke and its harnesses.

CI limits and recovery: [CI job timeouts](testing-verification/ci-job-timeouts.md).

## Methods

A method is the registered contract for one kind of proof: runner, optional
capability kind, verdict path, evidence contract, and success policy. The
built-in roster is:

- **Command** — deterministic worktree command; exit 0 passes and captured
  output is evidence.
- **Browser check** — browser assertions with an automatic verdict.
- **Browser inspection** — screenshots judged against the expected outcome.

The `machine-qa` Pack adds **Terminal check**, **Terminal inspection**, and
**Machine state check**. Those methods share the registered `host_control`
runner and a serial `test-machine` capability.

Inspect the roster and a method contract with:

```text
yoke qa method list --project <project>
yoke qa method get <method-id> --project <project>
```

Built-in, Pack-registered, and project-local sources remain distinct. A method
selects registered code; case instructions never become a runner.

## Test plans

A test plan is a named, project-scoped, ordered sequence of cases. Every case
has a stable slug key, its own method, instructions, and expected outcome, so
one plan may mix command, browser, terminal, and machine proof.

```text
yoke qa plan create <slug> --project <project> --environment <site>/<name> --name "<name>"
yoke qa plan edit <slug>
yoke qa plan get <id> --project <project>
```

`qa plan edit` resolves project context from `--project`, then `YOKE_PROJECT`,
then the machine-config checkout mapping. It opens a clean JSON authoring
document in `$VISUAL`, `$EDITOR`, or `vi` and compare-and-swap saves plan
metadata plus the complete ordered case set. Invalid JSON, an editor failure,
or a concurrent edit preserves the temporary document and refuses the write.
An unchanged document preserves the plan timestamp and its case row identities.
The lower-level `qa plan-cases replace` adapter remains available for callers
that already hold a numeric plan id and intentionally replace cases only.

Attach a reusable plan as a project default for one workflow transition:

```text
yoke qa project-default set \
  --project <project> --plan-id <id> \
  --workflow <workflow> --transition <stage>
```

Or attach it to one item:

```text
yoke qa item-plan attach \
  --item <PREFIX-N> --project <project> --plan-id <id> \
  --transition <stage>
```

At the declared transition, Yoke materializes one requirement per case.
Those rows are the snapshot; a later plan edit does not reach them, and says
so. Once any requirement for a plan and transition exists,
the whole plan is considered snapshotted for that item; newly authored cases
do not leak into that item on a later materialization call. Empty plans cannot
be attached or materialized. v1 accepts only the `all-pass` policy, including
case-level overrides, and project-local methods can only be used by plans in
that same project. Case waiver stays case-scoped, and the transition
consumes the union of all materialized outcomes. Where QA policy is optional item attachment, attach and materialize accept only the selection in
`workflow_posture.verification`; set it on an item that has none with `yoke workflows item-posture amend PREFIX-N --verification-plan ID_OR_SLUG --reason TEXT` (`--help` carries the per-key decision tree).

A plan edit writes the plan alone and reports `requirements_behind_plan` — the
already-materialized rows it did not reach. Bringing those current is one
operation, which refuses rather than move a row a live walk or an in-flight
admitted copy has frozen: [Plan case currency](qa-platform/plan-case-currency.md).

```text
yoke qa plan rematerialize --item <PREFIX-N> --transition <stage>
```

Before an item can enter any terminal lifecycle stage, its QA records must be
settled. A run without a verdict (including a timed-out run), or an active,
waiting, or review-pending plan execution blocks the transition even when other
QA gates are bypassed. Complete the run with its verdict, or waive the
requirement, while the item claim is still active; terminal records are not
correctable afterward.

A deployment run can instead own one named plan directly, without inventing an item or workflow transition. Frozen stage/member execution is documented in [Deployment QA Stage Execution](qa-platform/deployment-stage-execution.md):

```text
yoke qa plan run \
  --deployment-run-id <run-id> \
  --plan <plan-slug> \
  --project <project>
```

The command verifies that the run and plan belong to the same project,
idempotently snapshots the plan cases onto
`qa_requirements.deployment_run_id`, and executes the server-issued roster.
The durable cursor and selected Test Machine lease are bound to that deployment
run; normal QA runs, artifacts, and verdicts remain attached to the
materialized requirements. Host control always uses the registered
two-phase execution protocol.
If any case uses an agent verdict path, deterministic capture finishes first
and the command returns `state="awaiting_agent_review"` with exit `12`. The
returned typed dispatch contract is mandatory: the harness dispatches its
reviewer over the immutable bundle, and that reviewer submits one verdict and
rationale per case through the exact returned command. Until then the gate is
unsatisfied and the result reads `review_status="pending"`: no verdict, not a
pass, and a capture-side verdict is refused. Agent `undetermined` needs attached
evidence and halts the item until an owner or operator resolves its Inbox
request. A case that did not run records failure or `blocked_on_precondition`.
When reading the result, pass `deployment_run_id` to `qa.plan.get` to avoid
mixing another item or run's latest proof into the plan view.
`qa.activity.list` carries that field on every row and filters on it, and takes `item_ids` for the other direction — one item's own checks, which need no deployment run, bounded
per item so no subject crowds out another; `qa.artifact.read` resolves member evidence from the member's project and run QA evidence from the run's project.

## Capabilities and secrets

Capability availability is: not configured, configured (verified_at unset), ready, in use, or error.
`configured_unverified` is bookkeeping (`verified_at` is NULL), not a health claim; browser profile authorization is `yoke qa browser status`.
Serial resources queue while in use; that does not prevent plan attachment.

A project may register several `test-machine:<resource_name>` rows, one per
physical host. Resource names are global; `QA_HOST:<resource_name>` admits
one execution at a time. Machine-backed plans prefer a free verified machine,
then stable name, and report why. A run's machine pin is subordinate to durable
case `method_config.machine` constraints.

Settings and operation receipts are live capability facts. Read them with
`yoke test-machine list --project P` or `yoke test-machine get --project P
--machine NAME`; read each command's `--help` for its projection. Hostnames,
users, golden paths, desktop routes and cloud instance ids belong in those
project records. Capacity-machine registration grants launch capacity and
relay identity separately; it does not grant Test Machine readiness.

All host setup, sign-in, permissions, desktop access, baseline saving/restoration
and recovery live in the Machine QA Pack's complete ordered per-OS procedures:

- [macOS](../packs/machine-qa/versions/1.3.7/files/docs/packs/machine-qa/macos-host-provisioning.md)
- [Linux](../packs/machine-qa/versions/1.3.7/files/docs/packs/machine-qa/linux-host-provisioning.md)
- [Windows/WSL2](../packs/machine-qa/versions/1.3.7/files/docs/packs/machine-qa/windows-host-provisioning.md)

The [provisioning index](../packs/machine-qa/versions/1.3.7/files/docs/packs/machine-qa/host-provisioning.md) also installs
as `docs/packs/machine-qa/host-provisioning.md`. Use that installed copy for a
customized project. [Operation contracts](testing-verification/test-machine-operations.md)
explain leases and receipts; [baseline semantics](testing-verification/test-machine-golden-baseline.md)
explain what the evidence establishes.

Secret values never belong in settings, workflow definitions, item bodies,
prompts, logs, captures or artifacts. Capability-owned machine-local secrets
are resolved only for the subprocess that needs them and redacted from evidence.

## Evidence

The QA screen renders case outcomes and artifacts through the registered
artifact read surface, which lands bytes at a readable path it reports as
`path` and omits the presigned download URL from that output. Captures and
review bundles hand back that command. Durable handles presign short-lived
downloads; the rest reads as on-machine or not portable
([capture connections and repair](testing-verification/evidence-portability.md)).

```text
yoke qa activity list --project <project>
yoke qa artifact read --requirement-id <id> --artifact-id <id>
```

Missing or blocked evidence is never a silent pass. Machine baselines run as
registered operations inside the capability lease, verify the exact
branch-determining host state, and block dependent cases if the baseline cannot
be reached or verified.

## Source verification recipes

Run a direct command against the current session's claimed lane with
`yoke dev run -- <command>`. It reports every checkout-owned import origin and
preserves the caller's connected-environment selection: source location changes,
control-plane selection does not. Prod-flagged schema guards still apply.
Pytest runners isolate their test environment; Ruff and changed-test fallback
recipes live in [source-development.md](testing-verification/source-development.md).

## Which tree a run verified

A green says nothing until the tree it came from is named. A pytest run
rooted outside the calling session's claim-bound worktree is refused,
because it reports a pass for code nobody changed. The refusal names the
claimed worktree and the tree the run would have used. A session with no
claimed lane (inline skill work, main-checkout source-dev) passes through
untouched.

The check lives at the pytest startup layer, in the repo root
`conftest.py`, so the shape of the invocation does not matter: the
watcher wrapper, `run_tests`, the `worktree_run` QA case runner, a bare
`python3 -m pytest`, and an IDE run button all inherit it. The three
entry points above still judge the tree first, so their refusal arrives
before pytest starts at all; each hands the child process a marker so the
startup check costs no second lookup, and the xdist workers inherit that
same answer. A refused run stops before collection — one line on stderr,
exit status 3, nothing collected and no cluster started.

```bash
yoke watch pytest --allow-tree-mismatch --impacted main --bounded
python3 -m pytest --allow-tree-mismatch runtime/api/domain
```

`--allow-tree-mismatch` is the deliberate cross-tree run, accepted by the
wrapper, by pytest itself, and by `yoke qa case run` / `yoke qa plan run`,
which run the gate through the same guard: it proceeds and prints one line
naming both trees, so the result stays attributable. The flag every refusal
advertises is real on every surface that can raise the refusal.

A claimed lane whose directory no longer exists gets its own refusal. A
merge retires the lane row in the same act that removes its directory
(`item_worktrees.release_merged_lane`), so this state means the row was
stranded rather than retired; telling that reader to `cd` into the recorded
path would name a directory that is gone. The refusal instead names the two
recoveries that work — re-materialize the lane with
`yoke direct-workflow worktree prepare <item> --workflow <workflow>`, or
pass `--allow-tree-mismatch` to verify the tree as it stands.

Records carry the same fact. A QA run's `raw_result` and a Dash execution
evidence section both hold a `verification_tree` of worktree root plus
HEAD sha, so a green produced against the wrong tree cannot be recorded
indistinguishably from one produced against the right tree. The client
resolves that identity — only the machine holding the checkout can — and
`yoke direct-workflow dash evidence` accepts `--tree-root` /
`--tree-head-sha` when evidence is recorded from somewhere other than the
tree that was verified.

## Full-suite authority: CI

Per-project extras, groups, and test-root trees are declared on the
`test_environment` capability and Project Structure `test_roots`; see
[`project-test-environment.md`](testing-verification/project-test-environment.md).

Off-machine CI runs the full three-anchor suite on the pull request, on
the merge queue's merge_group ref (one gate per train's combined head),
and on the merged `main` commit. Verification stays change-scoped while
implementing: impacted selection to iterate; the QA case run is the one
full execution. For a project declaring a `ci_workflow_file` capability
that iteration selection also runs off-machine — `yoke watch pytest` and
the generic runner push the lane commit, dispatch the project's selection
workflow against it with the merge base, and adopt its conclusion — so
the workstation serves sessions while CI runs tests. `--local` (or
`YOKE_PYTEST_LOCAL=1`) is only a small targeted check expected to finish
in about one minute; uncommitted work does not justify a slow local run.
A remote run refuses an uncommitted tree — commit, then run on CI.
Queue landing (`yoke merge item --wait`) returns immediately when the
pull request's required checks have already concluded red with nothing in
flight — that is a terminal required-check failure, not a record-wait timeout.

Selection output distinguishes pytest files from collected items as
`files=N of M items=X of Y`; unavailable values are explicit as `unknown`.
A bounded unbounded-verdict names the rule, runnable subset, and coverage
deferred to the final QA gate. Conftest fixture use and function-id
dispatch are selection edges, not triggers. Trigger paths are excluded from reachability;
selecting 80% of a universe of at least 100 files gets the same deferral,
and the watcher repeats the file/item summary after collection.

That contract — the iteration loop, why the same tree is never proved
twice, how to read a widened selection, the CI-disagreement triage, and
the red-main and CI-outage protocols — lives in
[`testing-verification/full-suite-authority.md`](testing-verification/full-suite-authority.md).

## Concurrent local runs

One disposable PostgreSQL cluster serves every test invocation on the
machine, and any number of them may run at once. How the run tag keeps
them out of each other's databases, how heavy sweeps queue behind the
machine-wide admission slot, how the orphan sweep reclaims what an
interrupted run left, and why a run that named no cluster of its own may
not borrow an administered one all live in
[`testing-verification/concurrent-local-runs.md`](testing-verification/concurrent-local-runs.md).
Local runs also share one machine-wide pytest-xdist worker budget, since the
admission slot deliberately lets file-scoped runs past it and their sum is
what saturates a workstation; that doc covers it too.

Doctor checks every prod-flagged local-Postgres connection this machine knows
for leftover `yoke_test_run*` databases. A finding stays manual: its report
prints a dry-run review command and the explicit removal command for that
connection; Doctor never drops a database itself.

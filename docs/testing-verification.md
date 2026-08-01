# Testing and Verification

Yoke presents QA as test plans, methods, capabilities, and readable outcomes.
Requirements, runs, and artifacts remain execution records created by Yoke and
its harnesses.

## Methods

A method is the registered contract for one kind of proof: executor, optional
capability kind, verdict path, evidence contract, and success policy. The
built-in roster is:

- **Command** — deterministic worktree command; exit 0 passes and captured
  output is evidence.
- **Browser check** — browser assertions with an automatic verdict.
- **Browser inspection** — screenshots judged against the expected outcome.

The `machine-qa` Pack adds **Terminal check**, **Terminal inspection**, and
**Machine state check**. Those methods share the registered `host_control`
executor and a serial `test-machine` capability.

Inspect the roster and a method contract with:

```text
yoke qa method list --project <project>
yoke qa method get <method-id> --project <project>
```

Built-in, Pack-registered, and project-local sources remain distinct. A method
selects registered code; case instructions never become an executor.

## Test plans

A test plan is a named, project-scoped, ordered sequence of cases. Every case
has a stable slug key, its own method, instructions, and expected outcome, so
one plan may mix command, browser, terminal, and machine proof.

```text
yoke qa plan create <slug> --project <project> --name "<name>"
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
Those rows are the snapshot: later plan edits affect only items that have not
materialized the plan. Once any requirement for a plan and transition exists,
the whole plan is considered snapshotted for that item; newly authored cases
do not leak into that item on a later materialization call. Empty plans cannot
be attached or materialized. v1 accepts only the `all-pass` policy, including
case-level overrides, and project-local methods can only be used by plans in
that same project. Case rerun and waiver stay case-scoped, and the transition
consumes the union of all materialized outcomes.

A deployment run can instead own one named plan directly, without inventing
an item or workflow transition:

```text
yoke qa plan run \
  --deployment-run-id <run-id> \
  --plan <plan-slug> \
  --project <project>
```

The command verifies that the run and plan belong to the same project,
idempotently snapshots the plan cases onto
`qa_requirements.deployment_run_id`, and executes the server-issued roster.
The durable cursor and serial Test Mac lease are bound to that deployment
run; normal QA runs, artifacts, and verdicts remain attached to the
materialized requirements. Host control always uses the registered
two-phase execution protocol.
If any case uses an agent verdict path, deterministic capture finishes first
and the command returns `state="awaiting_agent_review"` with exit `12`. The
returned typed dispatch contract is mandatory: the harness dispatches its
reviewer over the immutable bundle, and that reviewer submits one verdict and
rationale per case through the exact returned command. The gate remains
unsatisfied while dispatch is pending. Only an agent `inconclusive` verdict
creates human Inbox work.
When reading the result, pass `deployment_run_id` to `qa.plan.get` to avoid
mixing another item or run's latest proof into the plan view.
`qa.activity.list` includes that field on every row and accepts it as an
optional filter; `qa.artifact.read` resolves evidence from the run's owning
project without an item join.

## Capabilities and secrets

A capability is the configured resource a method may need. Its availability
is one of: not configured, configured (unverified), ready, in use, or error.
Serial resources queue while in use; that does not prevent plan attachment.

The Test Mac is one `test-machine` capability, not three separate resources.
Inspect, update non-secret settings, and verify it with:

```text
yoke test-machine get --project <project> --json
yoke test-machine settings-replace \
  --project <project> --settings-file <settings.json> \
  (--new | --base '<as-read-json>')
yoke test-machine verify --project <project>
```

Provision the host once before saving the capability:

1. Create a dedicated macOS test user and make the host reachable through a
   private network.
2. Enable **System Settings → General → Sharing → Remote Login** for that user,
   install the operator public key in `~/.ssh/authorized_keys`, and verify a
   batch SSH login. Do not expose SSH with router port forwarding.
3. Verify either `tmux` or GNU Screen is available with
   `command -v tmux || command -v screen`. `host_control` detects the backend,
   preferring `tmux` when both exist. The dedicated Test Mac uses its existing
   `screen` command; do not add Homebrew or `tmux` only for this integration.
4. In **System Settings → Privacy & Security**, grant the logged-in
   Terminal.app Automation access to Terminal and Screen Recording access.
   Keep the Mac logged in and unlocked for screenshots. These are interactive
   macOS permission grants on the host, not credentials or tokens that Yoke
   stores.
5. Disable automatic system and display sleep for the test interval. Restore
   the operator's normal sleep policy when the dedicated test interval ends.

The saved settings document contains exactly `resource_name`, `host`, `user`,
and `operating_notes`. It contains no credentials. `ssh_private_key` is the
only Test Mac credential. Store it on the machine that runs `host_control`:

```text
printf '%s' "$SSH_PRIVATE_KEY" | yoke projects capability secret set \
  --project <project> --cap-type test-machine \
  --key ssh_private_key --value-stdin
```

The private key value is the key material, not a path. Yoke writes it to a
capability-owned machine-local file with restricted permissions. Do not copy
it to the remote host, the project checkout, or control-plane settings. Host
baselines run as the dedicated test user and do not invoke `sudo`; no sudo
credential is required. After provisioning or changing any setting, SSH key,
or required macOS permission, run `yoke test-machine verify`; the capability
is not ready until connectivity and terminal-control checks pass.

Secret values never belong in settings JSON, workflow definitions, item
bodies, prompts, logs, captures, or artifacts. The executor receives resolved
secrets only for its subprocess and must redact them from evidence.

The registered `fresh-host` baseline performs the complete installer reset as
the dedicated test user, using only guaranteed macOS shell primitives. It
removes Yoke and uv state, launchers, temporary installer files, managed and
handwritten tool-path startup entries, and the children of `~/code`. It
preserves stage and production token bytes opaquely in mode-restricted
`~/yoke-smoke-tokens`, relocates prior campaign evidence into a mode-restricted
`~/yoke-smoke-evidence/reset.*` directory, and then proves `.yoke`, command
resolution, and the split login PATH are clean before emitting
`YOKE_MAC_WIPE_OK`. It never removes `.ssh` or Command Line Tools; returning a
Mac to a no-Command-Line-Tools state remains a separate destructive operator
decision.

## Evidence

The QA screen renders case outcomes and artifacts through the registered
artifact read surface. Durable handles use authorized short-lived downloads;
machine-local handles render on the owning machine and appear elsewhere as an
explicit on-machine or not-portable state.

```text
yoke qa activity list --project <project>
yoke qa artifact read --requirement-id <id> --artifact-id <id>
```

Missing or blocked evidence is never a silent pass. Machine baselines run as
registered operations inside the capability lease, verify the exact
branch-determining host state, and block dependent cases if the baseline cannot
be reached or verified.

## Source verification recipes

Ruff is a locked development dependency. Lint every changed Python path with:

```bash
uv run --frozen ruff check <changed Python paths>
```

Do not call a checkout-local `.venv/bin/ruff` path or rely on an ambient
Homebrew install.

For a changed-test fallback, first list candidates with:

```bash
git diff --name-only --diff-filter=ACMR <base>...HEAD \
  -- ':(glob)**/test_*.py' ':(glob)**/*_test.py'
```

Review the newline-delimited output, then pass the exact existing paths to
`watch_pytest`. Do not pipe NUL-delimited Git output through `rg -z`, and never
feed a filter diagnostic to pytest as a filename.

## Full-suite authority: CI

The full three-anchor suite runs off-machine in CI on both the pull request
and the merged commit on `main` (`.github/workflows/yoke-ci.yml` triggers on
`pull_request` and `push` to `main`). The protected merge path requires the
PR checks, so every merge carries one complete pre-merge sweep, and the push
trigger re-proves the true merge commit afterward. Local verification stays
change-scoped:

- **While implementing** — run the impacted selection over the branch diff:

  ```bash
  uv run --frozen python3 -m yoke_core.tools.watch_pytest --impacted main
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

### When CI disagrees with the local run

Impacted selection makes a falsifiable claim: *this change cannot affect
that test*. Every CI failure gets triaged against that claim before
anything else:

- **The failing test was not in the local selection** — the reachability
  model missed a dependency edge. That is a selector defect, never noise.
  Root-cause the coupling the import graph could not see (the residual
  blind spots for `.py`-only changes are non-import coupling: subprocess
  module invocations, string-target patching, runtime string dispatch),
  then extend `FULL_SWEEP_TRIGGERS` or the index modeling **and add a
  regression test to the selector's own tests in the same fix**. The
  selector only stays trustworthy if every counterexample tightens it.
- **The failing test was selected and passed locally** — an environment
  difference, not a selection miss: CI runs Python 3.10 and 3.13 shards
  on Linux while local runs one interpreter on macOS, plus concurrency,
  ordering, and neighbor-merge interactions. No local selection can catch
  this class; it is exactly why CI is the authority.

### Red-main protocol

A failing `push`-to-`main` CI run means a merge landed broken despite green
PR checks (a semantic conflict with a neighboring merge, or a selection
miss per the triage above). Whoever merged the commit that turned main red
owns the response: revert or fix forward immediately, before merging
anything else on top — and when the triage says selection miss, the
selector fix ships with it. Treat the failing run's first red shard as
that work's evidence, not a background alarm.

### CI-outage fallback

When CI is unreachable, the local full gate returns as the documented
exception:

```bash
uv run --frozen python3 -m yoke_core.tools.watch_pytest -- runtime/api/ runtime/harness/ tests/
```

Record in the verification evidence that the local sweep substituted for CI
and which commit it covered. Never merge with neither proof.

## Concurrent local runs

One disposable PostgreSQL cluster serves every test invocation on the
machine, and any number of them may run at once — a full three-anchor gate,
a second gate, and a raw `uv run --frozen python3 -m pytest <one file>` all
at the same time. Isolation comes from the database names rather than from a
cluster per run:

- Every database an invocation creates carries that invocation's run tag,
  minted once and published through `YOKE_TEST_RUN_TAG` so pytest-xdist
  workers share their controller's identity.
- An invocation may only ever drop databases carrying its own tag. Nothing a
  running suite does can reach another run's databases.
- Databases left behind by an interrupted run are reclaimed by an orphan
  sweep that first confirms the owning process has exited, then drops with
  `FORCE` under a bounded statement timeout.

The sweep never sits in a starting suite's critical path. Cluster preparation
launches it detached and returns immediately, because dropping a database is
seconds of disk work on a loaded machine — a synchronous sweep of a large
backlog delayed pytest collection by minutes, which is the stall the cleanup
exists to prevent. One sweeper runs at a time (a lock file under the cluster
root; others skip instantly rather than queueing), and each pass stops at a
time budget, so a large backlog drains over several runs and reports how many
it deferred. Run one directly with:

```bash
python3 -m yoke_core.tools.pg_testcluster prune
```

Interrupting a run through `watch_pytest`, `run_tests`, or a QA registered
command terminates and reaps the whole process group, so xdist workers do
not outlive the run and keep its databases open. Only `SIGKILL` can bypass
that, which is what the orphan sweep backstops.

`YOKE_PG_CLUSTER_ROOT` still points an invocation at a wholly private
cluster. That is an escape hatch for a wedged shared cluster, not the normal
isolation mechanism — a full `initdb` per run would slow ordinary iteration
without adding safety the run tag does not already provide.

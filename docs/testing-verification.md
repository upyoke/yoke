# Testing and Verification

Yoke presents QA as test plans, methods, capabilities, and readable outcomes.
Requirements, runs, and artifacts remain execution records created by Yoke and
its harnesses.

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
Those rows are the snapshot: later plan edits affect only items that have not
materialized the plan. Once any requirement for a plan and transition exists,
the whole plan is considered snapshotted for that item; newly authored cases
do not leak into that item on a later materialization call. Empty plans cannot
be attached or materialized. v1 accepts only the `all-pass` policy, including
case-level overrides, and project-local methods can only be used by plans in
that same project. Case waiver stays case-scoped, and the transition
consumes the union of all materialized outcomes. Where QA policy is optional item attachment, attach and materialize accept only the selection in
`workflow_posture.verification`; set it on an item that has none with `yoke workflows item-posture amend PREFIX-N --verification-plan ID_OR_SLUG --reason TEXT` (`--help` carries the per-key decision tree).

If a plan definition needs correction after it has materialized, replace the
active snapshot with:

```text
yoke qa plan rematerialize --item <PREFIX-N> --transition <stage>
```

The operation refreshes matching plan requirements in place, retains their run
history, creates any newly added cases, and waives cases no longer in the plan.

Before an item can enter any terminal lifecycle stage, its QA records must be
settled. A run without a verdict (including a timed-out run), or an active,
waiting, or review-pending plan execution blocks the transition even when other
QA gates are bypassed. Complete the run with its verdict, or waive the
requirement, while the item claim is still active; terminal records are not
correctable afterward.

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
The durable cursor and selected Test Mac lease are bound to that deployment
run; normal QA runs, artifacts, and verdicts remain attached to the
materialized requirements. Host control always uses the registered
two-phase execution protocol.
If any case uses an agent verdict path, deterministic capture finishes first
and the command returns `state="awaiting_agent_review"` with exit `12`. The
returned typed dispatch contract is mandatory: the harness dispatches its
reviewer over the immutable bundle, and that reviewer submits one verdict and
rationale per case through the exact returned command. The gate remains
unsatisfied while dispatch is pending. Agent `undetermined` is allowed only
with attached evidence; it halts the item until a project owner or operator
resolves the Inbox request. A case that did not run records failure or
`blocked_on_precondition` and returns to its scheduler without human work.
When reading the result, pass `deployment_run_id` to `qa.plan.get` to avoid
mixing another item or run's latest proof into the plan view.
`qa.activity.list` includes that field on every row and accepts it as an
optional filter; `qa.artifact.read` resolves evidence from the run's owning
project without an item join.

## Capabilities and secrets

Capability availability is: not configured, configured (unverified), ready, in use, or error.
Serial resources queue while in use; that does not prevent plan attachment.

A project may register several `test-machine:<resource_name>` rows, one per physical host.
Resource names are global: one project may register each, and the matching
`QA_HOST:<resource_name>` lease admits one execution at a time. Machine-backed
plans prefer a free verified machine, then stable name, and report why. Pin a
run with `yoke qa plan run --machine NAME`; durable `method_config.machine`
case constraints take precedence. Explicit reads, settings updates, and
verification also select one machine by name:

```text
yoke test-machine list --project <project> --json
yoke test-machine get --project <project> --machine <resource-name> --json
yoke test-machine settings-replace \
  --project <project> --machine <resource-name> --settings-file <settings.json> \
  (--new | --base '<as-read-json>')
yoke test-machine verify --project <project> --machine <resource-name>
```

Provision the host once before saving the capability. The general procedure —
disk encryption, automatic login, sleep, remote access and its separate full
disk access grant, developer tools, privacy grants, and authenticated harness
CLIs, each with an observable check — ships in the
[`machine-qa` Pack](../packs/machine-qa) and installs as
`docs/packs/machine-qa/host-provisioning.md`. Follow it there; a second copy
here is how this checklist went stale before.

This project's Test Mac fleet adds only host-specific facts:

| Resource | Host/user | Golden baseline and fixture notes |
| --- | --- | --- |
| `test-mac` | `testys-mac-mini.taile868e2.ts.net` / `testy` | `/Users/Shared/yoke-golden/testy-home-20260826`; Apple Silicon |
| `test-mac-pro` | `bens-mac-pro.taile868e2.ts.net` / `oxpecker` | `/Users/Shared/yoke-golden/oxpecker-home-20260831`; Intel MacPro6,1, macOS 12.7.6, APFS, no T2, FileVault off; Ethernet `00:3e:e1:c8:4e:a5`; every other login and home excluded; Codex.app intentionally absent while its CLI is signed in |
Both use existing GNU `screen`, stable private-network names, and no preprovisioned Yoke or `tmux`.

The `machine_browser_approval` gate self-approves in the host's visible Safari
session (`self_approving: true` on `machine_qa.operator_gate`). No operator
browser action is needed; redeeming the one-time code in another browser
consumes it and breaks the gate (`machine_browser_tab_missing`).

The saved settings document contains `resource_name`, `host`, `user`,
`operating_notes`, and an optional `golden_baseline_path`. No credentials. `ssh_private_key` is the
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
or required macOS permission, run `yoke test-machine verify --project <project>
--machine <resource-name>`; that machine is not ready until connectivity and
terminal-control checks pass. That command
is **destructive** — it performs the full host reset before installing the
current release. It is a readiness gate, not a reachability probe; answer "can
I see the machine?" with a plain SSH command.

Secret values never belong in settings JSON, workflow definitions, item
bodies, prompts, logs, captures, or artifacts. The runner receives resolved
secrets only for its subprocess and must redact them from evidence.

The registered `fresh-host` baseline restores the host's declared golden
baseline. Its target state is USER-EQUIVALENT, not bare: a real user arrives
with harness apps installed and signed in, so a machine stripped to nothing is
not a fresh host. What the golden must carry, which programs it must have
signed in as declared by its adjacent `.probes` sidecar, the illustrative
current three-probe snapshot, how to capture one, and how to read a probe that
fails:
[`testing-verification/test-machine-golden-baseline.md`](testing-verification/test-machine-golden-baseline.md).

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

Run a direct command against the current session's claimed lane with
`yoke dev run -- <command>`. It reports every checkout-owned import origin
before execution. Ruff and changed-test fallback recipes live in
[source-development.md](testing-verification/source-development.md).

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
and on the merged `main` commit. Local verification stays change-scoped:
impacted selection to iterate; the QA case run is the one full execution.
Queue landing (`yoke merge item --wait`) returns immediately when the
pull request's required checks have already concluded red with nothing in
flight — that is a terminal required-check failure, not a poll-budget timeout.

Selection output distinguishes pytest files from collected items as
`files=N of M items=X of Y`; unavailable values are explicit as `unknown`.
A bounded unbounded-verdict names the rule, runnable subset, and coverage
deferred to the final QA gate. Trigger paths are excluded from reachability;
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

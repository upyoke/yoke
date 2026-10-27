# Case starting state and activity

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Verification](index.md) > Starting state and activity
<!-- /yoke:breadcrumbs -->

Declare a Machine case's starting state and read its subject, execution and evidence through the shared activity projection.

## Machine case starting state

Test Machine cases (`host_control` and exploratory missions declaring a host)
declare starting state. A hostless mission explores on the controller and
declares no host starting state. Authoring, `qa.requirement.add`, and materialization refuse missing state;
`HC-qa-plan-machine-starting-state` fails stored cases missing it, and
`yoke qa plan get` shows each choice:

- `host_baselines: ["fresh-host"]` (or `shell-preconfigured`, or both): the
  runner resets to each named baseline; one requirement row per baseline. [Temporary cleanup](test-machine-desktop.md) preserves baseline/home/live scratch and reports freed space.
  Correct only one failed baseline with `--replaces-requirement FAILED_ID` on
  `yoke qa plan run` or materialize; the correction plan retains its case key.
- `"starting_state": "inherit"`: start on the machine exactly as the case
  directly before it in the plan left it, at the same baseline position. The
  first case cannot inherit, and no case may inherit after a mission. A mission
  may inherit only at the chain's tail, on the same driver, in an isolated
  execution; [Machine partitions](deployment-plan-execution.md#machine-partitions)
  explains host custody and the standalone plan boundary.
- `"starting_state": "as_is"` with `"starting_state_reason"`: run on the
  machine as found, for the stated reason.

On macOS, a failed captured-entry copy retries once to handle entries a live
service recreates during restore. A persistent failure retains the named
unrestored-entry receipt and copier diagnostic. Inspect that entry and repair
its permissions or service contention before retrying reset.

For a continuity case that needs earlier machine state, add
`method_config.continuity_fingerprint` to its `as_is` configuration: an object
mapping 1..16 absolute or `~/` stable file paths to recorded lowercase SHA-256
hashes. Record the hashes while the intended state is present under the host
lease, save the plan, and rematerialize its cases. For example, retain the
method's other fields and add:

```json
{"continuity_fingerprint":{"~/qa-state/conversation.json":"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"}}
```

That example hash is for a file containing exactly `abc`; record your own
with `python3 -c 'import hashlib,pathlib; print(hashlib.sha256(pathlib.Path("qa-state/conversation.json").read_bytes()).hexdigest())'`
on the leased machine from its home directory. Choose stable regular files
that prove the needed state, such as the required conversation artifact;
mutable databases, login stores and symlinks are unsuitable. The runner
checks before setup, and missions check again at walk-start. Missing, changed,
unreadable or uncheckable files refuse as `continuity_lost` without starting
the case. These contracts use `host-control-continuity-v1`, so an older
runner refuses the protocol instead of ignoring the check; upgrade the CLI
before retrying. Restore and prove the required state before recording replacement
hashes. `as_is` alone keeps the state it finds; it does not reserve a machine
between leases. Fingerprints detect loss; they do not prevent another lease
from resetting the host.

A case added on its own (`yoke qa requirement add`) belongs to no plan, so it
takes `--host-baseline NAME` or `--starting-state as_is
--starting-state-reason TEXT` and cannot inherit.
Before anything has run a case — no QA run, no plan result, not in a live
execution's roster — re-declare its starting state with `yoke qa requirement
update --requirement-id N --field starting_state --value
'{"starting_state":"as_is","starting_state_reason":"..."}'` (or
`{"starting_state":"baseline","host_baseline":"fresh-host"}`). It also rewrites
the row's in-flight admitted copies. Afterwards it refuses
`starting_state_case_executed` and names the corrected-case route. An item row
materialized from a plan refuses `starting_state_plan_owned`: edit the plan
case instead. `inherit` is declared only on a plan case.

A Terminal case (`terminal-check`, `terminal-inspection`) also names
`entry_surface`, the command the Terminal runs first (for example
`{yoke_bin} setup --connect https://app.upyoke.com --project-mode
machine-only`), and `required_completion`, the step that proves it finished.
Authoring, `qa.requirement.add` and materialization run the runner's own
recipe check and refuse `terminal_case_fields_missing` naming the missing
fields; only a plan case carries them, so fix it with `yoke qa plan edit
PLAN_SLUG` and `yoke qa plan rematerialize`. A requirement materialized before
this check refuses `machine_qa_recipe_invalid` before its starting-state
reset, so the host is never touched.

On macOS a `terminal-inspection` capture is issued from its own Terminal
window. That window is placed before its command starts, and the capture waits
until the capture and app windows' bounds are read back; an overlap is moved
clear, then minimized. If the overlap persists or the bounds cannot be read,
the image is kept and the run records `capture_degraded_reason` naming
`terminal_capture_window_overlaps_app` or
`terminal_capture_window_bounds_unreadable`, with both bounds and the recovery.
Judge that checkpoint from its transcript, and read the step's
`screenshot_diagnostics.capture_window_clearance` for the observed bounds.


A named-baseline or as-is case opens a chain; the inheriting cases behind it
extend it. `yoke qa plan run` runs every case at one baseline position before
the next, resets before each chain, and restores the chain's starting baseline
after its last case, and after any case that did not pass, recording the
receipt as `starting_state_restore` in that case's evidence. A failed reset
leaves the case unstarted (`starting_state_reset_failed`); a failed restore
stops the plan and names the `yoke test-machine reset` command. An inheriting
case whose predecessor did not pass in the same run is recorded
`blocked_on_precondition` (`inherited_predecessor_not_passed`) naming that
predecessor, and does not run. A failed or errored case blocks only its own
chain: the run continues with each later chain that starts from a named
baseline or `as_is`, then closes the execution once every case has a result,
naming the failed requirements in its reason (`qa-plan-case-failed`). The
review bundle for its completed captures lists the blocked cases and their
reasons under `chain_blocked`. A case that raises while running, a lost lease
or an operator abort still stops the whole execution.
Deployment-stage case selections keep each inheriting case directly behind its
predecessor. Requirements materialized before a plan declared its states read
as behind their plan: edit the plan, then refresh them.

## Select an item plan's source lane

```text
yoke qa plan run --item PREFIX-N --transition TRANSITION --checkout-path PATH --expected-branch BRANCH --expected-sha FULL_SHA
```

When an item has multiple active lanes, hold its matching item/task claim and
select the exact registered checkout and branch. The plan freezes each case's
path, branch and commit from that selected lane; an ambiguous selection or a
branch/path mismatch refuses with `qa_source_lane_unresolved` and names the
selection recovery. Read `yoke qa plan run --help` for other subjects.

An item plan run skips each case whose newest run, from `yoke qa plan run` or
`yoke qa case run`, passed at the item lane's recorded head and still matches
the case's method config and target. The remaining cases can span execution
targets, for example a no-target CI case and a production mission. One
execution has one target, so the run executes the first target's cases, then
starts the next target only after those passed; a stop leaves the rest as
`remaining_requirement_count`, and rerunning the same command continues. When
every case already passed at that head, the run refuses with
`qa_plan_roster_passed_at_candidate` and names the read and rerun commands.

## What the activity read returns

`yoke qa activity list --project P` returns summary rows: case and run
identity, timestamps, outcomes, proof summaries and evidence counts. It omits
case instructions, execution target JSON and artifact details. Use `--full`
for complete rows. To read one case's instructions, use its `requirement_id`:
`yoke qa requirement get --requirement-id N --full`.

`qa.activity.list` is scoped to **executable** cases: a case is in scope when
it carries a plan or a registered `method_id`. That covers plan-backed cases
and equally covers a case attached straight to an item or a deployment run
without one — an item's own ad hoc verification and a hand-authored release
check are as visible as anything the pipeline materialized. What stays out is
the method-less bookkeeping row (an acceptance-criterion marker), which never
executes, so it has no run, verdict, or evidence to show.

Project scope comes from whichever subject the row names — its plan, its item
or epic, or its deployment run — and the projects join is inner, so a row
whose project cannot be resolved that way is readable by nobody rather than by
every tenant. A planless case reports `plan_id`, `plan`, and `case_key` as
`null`; readers name it by `method_name` / `method_id` instead. The day
`summary` is computed from the same source as the rows, so its counts cover
exactly the checks the rows sit beside.

## Related

- [Case attachment](case-attachment.md)
- [Deployment plan execution](deployment-plan-execution.md)

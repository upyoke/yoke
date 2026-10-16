# Case starting state and activity

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Verification](index.md) > Starting state and activity
<!-- /yoke:breadcrumbs -->

Declare a Machine case's starting state and read its subject, execution and evidence through the shared activity projection.

## Machine case starting state

Test Machine cases (`host_control` and `exploratory-mission`) declare starting
state. Authoring, `qa.requirement.add`, and materialization refuse missing state;
`HC-qa-plan-machine-starting-state` fails stored cases missing it, and
`yoke qa plan get` shows each choice:

- `host_baselines: ["fresh-host"]` (or `shell-preconfigured`, or both): the
  runner resets to each named baseline; one requirement row per baseline. [Temporary cleanup](test-machine-desktop.md) preserves baseline/home/live scratch and reports freed space.
  Correct only one failed baseline with `--replaces-requirement FAILED_ID` on
  `yoke qa plan run` or materialize; the correction plan retains its case key.
- `"starting_state": "inherit"`: start on the machine exactly as the case
  directly before it in the plan left it, at the same baseline position. The
  first case cannot inherit, nor can a case follow or be a mission.
- `"starting_state": "as_is"` with `"starting_state_reason"`: run on the
  machine as found, for the stated reason.

A case added on its own (`yoke qa requirement add`) belongs to no plan, so it
takes `--host-baseline NAME` or `--starting-state as_is
--starting-state-reason TEXT` and cannot inherit.

A named-baseline or as-is case opens a chain; the inheriting cases behind it
extend it. `yoke qa plan run` runs every case at one baseline position before
the next, resets before each chain, and restores the chain's starting baseline
after its last case, and after any case that did not pass, recording the
receipt as `starting_state_restore` in that case's evidence. A failed reset
leaves the case unstarted (`starting_state_reset_failed`); a failed restore
stops the plan and names the `yoke test-machine reset` command. An inheriting
case whose predecessor did not pass in the same run is recorded
`blocked_on_precondition` naming that predecessor, and does not run.
Deployment-stage case selections keep each inheriting case directly behind its
predecessor. Requirements materialized before a plan declared its states read
as behind their plan: edit the plan, then refresh them.

## What the activity read returns

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

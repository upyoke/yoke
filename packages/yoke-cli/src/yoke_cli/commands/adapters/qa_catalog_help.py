"""Detailed teaching for QA catalog commands."""

from yoke_cli.commands.adapters.workflows_item_posture import (
    WORKFLOWS_ITEM_POSTURE_AMEND_RECIPE,
)
from yoke_contracts.qa_case_environment import (
    COMMAND_CASE_BASE_URL_ENV,
    COMMAND_CASE_DEPLOYMENT_MEMBER_ENV,
    COMMAND_CASE_DEPLOYMENT_RUN_ENV,
)


#: Read as ``yoke qa item-plan attach --help``.
ITEM_PLAN_ATTACH_EPILOG = (
    "Attaching adds a blocking QA requirement at --transition.\n\n"
    "A plan bound to the environment the item is delivered to cannot attach\n"
    "at a transition before delivery there: its revision check reads that\n"
    "environment, so it could never pass and the item could never be\n"
    "released. A plan bound to another environment still attaches. Attach\n"
    "the delivery plan at the item's post-deploy transition instead, with\n"
    "--qa-phase post_deploy. If you know the target is already reachable,\n"
    "pass --acknowledge-unreachable-target.\n\n"
    "To withdraw a wrong attachment that has not run, use\n"
    "yoke qa item-plan retract. The row stays as history; there is no detach.\n\n"
    "When the workflow's QA policy makes item attachment optional, a\n"
    "pre-merge attach accepts only the plan or method already chosen in\n"
    "workflow_posture.verification. Choose it first (choosing attaches\n"
    "nothing):\n"
    f"  {WORKFLOWS_ITEM_POSTURE_AMEND_RECIPE}\n"
    "Then attach with --transition reviewing-implementation\n"
    "--qa-phase verification, and run yoke qa plan materialize.\n\n"
    "Post-deploy plans attach directly at the pinned release stage with\n"
    "--qa-phase post_deploy; no choice step is needed.\n\n"
    "A plan this member already holds as a correction on an executing run\n"
    "is refused as qa_correction_already_held. Leave that correction on the\n"
    "run. Attach a different plan only for a separate obligation."
)

#: Read as ``yoke qa plan-cases replace --help``. What an author has to know
#: to write the case array, and what their command is handed when it runs.
PLAN_CASES_REPLACE_EPILOG = f"""\
The case array
--------------
Each case is a JSON object: case_key, method_id, instructions,
expected_outcome, and the method's own method_config. `position` is optional
-- omit it and each case takes its place in the array, which is the order you
wrote them in. Supply it only to state an order the array does not.

Source-authored plans
--------------------
Generated input is an object with source_revision and cases; qa plan-cases sync
records its provenance atomically. qa plan-cases replace accepts manual arrays.
--source-revision FULL_SHA records the merged exporter commit with the cases.
It must be an ancestor of the project's verified default branch. Once recorded,
every replacement needs source provenance; interactive editing refuses. A sync
moves only forward: the recorded revision itself or a descendant of it.
An older source refuses qa_plan_source_revision_regression, and a recorded
revision the repository cannot prove refuses qa_plan_source_ancestry_unverified;
both name the two revisions and write nothing. Export from current main and
sync again. Release materialization and refresh refuse
qa_plan_source_candidate_mismatch when that source is not carried by the
candidate: release a candidate carrying it, or keep corrections run-scoped.
A serving build missing source binding refuses before writing.

Case environment obligations
----------------------------
`target_envs` is an optional JSON list of unique registered environment names,
for example ["prod"]. It creates one requirement per environment and
host baseline. [] keeps the plan's default target. Each deployment QA stage
selects only cases that name its environment; done waits for every target's
accepted proof. Rematerialize compares the environment as part of case identity,
so a retained Stage obligation cannot disappear when Production passes.

Verify on production by default. A case naming an environment that does not
declare role.production true (stage) must set `stage_reason` to
creates_or_destroys_data or changes_infrastructure, else stage_reason_required
refuses it; a read-only check targets production instead.

Manual wake
-----------
`wake_path` is "automatic" (default: the case starts when its stage begins) or
"manual" (its owner is woken to check the evidence first). "manual" needs
`wake_evidence`: one line naming the real-traffic evidence a registered read
can confirm before the case can run, for example "a deployment run with at
least 44 members exists after this release". Missing evidence refuses
wake_evidence_required; evidence on an automatic case refuses
wake_evidence_without_manual_wake. Method, runner and verdict path are
unchanged. The stage driver wakes the owner once per open manual case to
check its evidence: run the case if it exists, otherwise ask the operator for a
waiver. The fleet report lists open cases under "waiting on manual wake".

What a Command case's shell is handed
-------------------------------------
{COMMAND_CASE_BASE_URL_ENV}: the target the case runs against.
{COMMAND_CASE_DEPLOYMENT_RUN_ENV}: the deployment run this case answers for.
{COMMAND_CASE_DEPLOYMENT_MEMBER_ENV}: the member that run is proving, as PREFIX-N.

The last two are set only for a case bound to a deployment run and member,
and they are how such a case names its own subject. A command that writes a
run id or a member ref as a literal is correct for exactly one run and then
reports on the wrong one; read these instead, and the same plan keeps working
on every release.

What this does NOT reach
------------------------
Replacing cases writes the plan. Rows already materialized from it keep the
body they were materialized with, so the result reports
requirements_behind_plan: each actionable row, the fields that moved, and the
`yoke qa plan rematerialize` invocation that reaches that exact row. An empty
list means no active subject is behind the plan. Done/cancelled items and
finished standalone walks stay as history, counted once in
historical_requirements_excluded_count. Read it — a correction that stops at
the plan is a correction the case that actually runs never received.
"""

#: Read as ``yoke qa plan materialize --help``: what a repeat call does to a
#: plan that already has rows, and where an amended row goes instead.
PLAN_MATERIALIZE_EPILOG = """Materializing a plan that already has rows
------------------------------------------
Materialization is convergent for added cases: every case the plan has
gained since the last call gets its row, and every row already there is
confirmed, never rewritten. A row whose case has since been amended keeps
its old body here; `yoke qa plan rematerialize` is what brings it current.
On an item, a live row whose case the plan no longer carries (the case was
replaced or removed) refuses qa_plan_rows_orphaned before any write, naming
each row: rematerialize retires it, superseding a replaced post_deploy row
with its successor or waiving a removed one.

--replaces CASE_KEY=FAILED_REQUIREMENT_ID declares the corrected case the
replacement of a failed one. A case it names gets no second, automatic
correction from the stage's own corrected plan, so the two never collide.
Use --replaces-requirement FAILED_REQUIREMENT_ID when that key spans host
baselines: the corrected plan keeps the failed case's key and creates only
its exact baseline. Other baselines keep their own obligations and evidence.
"""

#: Read as ``yoke qa plan rematerialize --help``. The one route from a
#: corrected plan to the rows that run it, and where it stops.
PLAN_REMATERIALIZE_EPILOG = """Bringing live rows to the plan's current text
---------------------------------------------
This is the supported way to correct a materialized case. It refreshes
matching rows in place, retains their QA run history, creates cases the plan
has gained, and retires cases it has lost. It reaches every executable column,
instructions and expected_outcome included -- which `yoke qa requirement
update` cannot write at all -- because it rewrites the derivation whole rather
than one allowlisted field. It also carries that body onto every admitted
deployment-stage copy frozen from a refreshed or newly created row that can
still be reached, reported as corrected_admitted_copy_ids -- otherwise the copy would keep the
old body and its stage would refuse the case as superseded.

An item transition whose plan a delivery already answered still has its
existing rows refreshed and its lost cases retired; it gains no new row there,
because only a run that already finished could answer one. The result's
plan_ids names every plan the call reached.

On an item transition, a lost post_deploy case that exactly one created row
replaces -- same item, transition, phase, environment and host baseline -- is
superseded by that row, reported as superseded_requirement_ids (old id to
successor id). The successor carries the obligation: a run that already
admitted the old case answers it through those copies, and later releases
admit only the successor. A lost case with no single successor is waived as
removed (waived_requirement_ids).

A deployment subject converges case by case, so one answered sibling never
blocks the rest: a row nobody has judged is refreshed in place; a case whose
rows all failed (or were discharged) and whose content has since changed gets
one corrected row, declared the replacement of the failed attempts -- they
keep their evidence and are superseded once it passes; a passed case stands
as its acceptance record; a case the plan lost is waived. A case already
carried by a declared replacement (an explicit --replaces) gets no second,
automatic one.
The subject keeps the deployment target its stage receipt pinned --
rematerializing never re-points a frozen run at the plan's current
environment. A declaration correction of the same environment identity, or a
snapshot whose endpoints already match the resolved environment while
its identity labels are stale, is not rematerialize's job:
`yoke qa requirement rebind-target` points the stored digest at the
live facts and keeps the recorded verdict. A live item requirement
cannot be superseded.

An item refresh considers shared copies only on runs it still belongs to.
Removed members leave shared rows and live walks to the remaining members.
--plan is a deployment-only filter; with --item, remove --plan and retry.

With --item and --stage, --plan selects by owner. A shared plan the member attaches
refreshes that shared group's run-wide rows. The member's own plan refreshes
only that member's rows, so a live run-wide walk of a shared plan does not
block it.

Live walks
----------
A live QA plan execution froze its roster from these rows. A case the walk
has not reached yet -- after its cursor, with no result recorded -- takes the
correction: its roster entry is rebuilt and the roster digest moves, so the
cases already passed keep their results. The walking `yoke qa plan run` stops
at its next check-in with qa_roster_corrected; run the same command again to
resume on the corrected roster.

Where it refuses instead
------------------------
It will not move a row something else has already frozen a copy of. A refusal
rolls the whole refresh back, so every row and roster stays exactly as it was.

qa_roster_case_reached: a changed case sits at or before a live walk's cursor,
or recorded a result ahead, or an unreached case would be retired, reordered
or retargeted. The refusal names the execution and the full
`yoke qa plan abort` invocation; abort, rerun the refresh, run the plan again.

plan_execution_in_flight: the refresh would add a case to a subject a live
walk is running; its roster cannot carry the new case. Abort with the named
`yoke qa plan abort` invocation, refresh, then run the plan again.

shared_plan_refresh_selection: --item with a --plan that is neither a
shared plan the member attaches nor one of its own materialized plans.

admitted_copy_in_flight: the refresh would change an admitted deployment-stage
copy that has answered or that a live walk has reached, on a run that is still
executing. A copy the refresh leaves unchanged never refuses. The refusal names
the copy, its run, and the remedy available for that copy.

Reading drift without two bodies
--------------------------------
`yoke qa requirement list` reports plan_currency per materialized row --
current, stale with plan_diverging_fields, orphaned, or unreadable.
"""

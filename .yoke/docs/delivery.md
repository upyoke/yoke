# Delivery

Workbench delivery has three destinations, and **Deployments** carries two
tabs because a flow definition and a run of it are two readings of one
subject:

| Destination | Meaning |
|---|---|
| **Deployments → Flows** | Pipeline definitions runs execute. Read-only here: definitions are authored by command. |
| **Deployments → Runs** | Each execution of a flow against an environment. Opening a row opens that run. |
| **Environments** | Deploy targets |
| **Databases** | Declared DB models, posture, apply records — see [databases-and-migrations.md](databases-and-migrations.md) |

Flows is the tab Deployments opens on. Runs live at `#/deployments/runs`, and
one run at `#/deployments/runs/<run id>`.
The run page reads that exact run across every project the viewer can access,
so its members include work from another project even when opened from a
project-filtered list. The list itself keeps its chosen project filter; run
checks and the target environment still belong to the run's owning project.

## Item-bound delivery

`/yoke usher` and `yoke deployment-runs start-for-item` bind implemented work
to a run, execute the pipeline, and move members toward done. Flow id ≠ run
id (`run-YYYYMMDD-NNN`).

Membership is not by itself completion. A member closes only on a succeeded
run with completion authority for it: a run of the item's own selected flow,
or another project's run that recorded a bound source commit for the item's
project. Carried code, a failed run, or a same-project run of another flow
does not close it. So a final-delivery release refuses, before it executes,
a same-project member whose selected flow it cannot close. The refusal names
both repairs: select the run's flow for the item, or cancel the run and
deliver the item on its own flow. When a release with that authority
succeeds, it stamps each member's delivery evidence and closes every member
whose item and shared gates have passed, with no holder re-running a merge.
Run success and those close-outs settle together. If any cleared member's
close-out would refuse, the run keeps its prior status and nothing closes.
Every claim and lane is kept, and the refusal names each member, its reason,
and the re-drive: `yoke deployment-runs update RUN status succeeded`.
When a no-change Dash that never opened a lane is left at its release wait,
its holder closes it with `yoke lifecycle transition PREFIX-N --to done`.
That transition still requires the succeeded run, QA, and approval.

## Hosting

There is no separate Hosting destination. Hosting shows up as:

- Packs (production-deploy, runners, environment infra, …)
- `/yoke onboard` gated first deploy
- Environment settings (projected scalar reads only — never dump whole
  settings documents)

## Disable vs delete

Disable a flow definition to stop new assignments while retaining history.
Definitions referenced by runs are immutable.

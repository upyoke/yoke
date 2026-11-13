# Deployments dashboard

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Deployments](index.md) > Deployments dashboard
<!-- /yoke:breadcrumbs -->

Read what the web dashboard shows about flows, runs and item delivery.

## Destinations

**Deployments** has two tabs, because a flow definition and a run of it are
two readings of one subject:

| Destination | Meaning |
|---|---|
| **Deployments → Flows** | Pipeline definitions runs execute. Read-only: create, version and disable them with `yoke deployment-flows create`, `version` and `set-status`. |
| **Deployments → Runs** | Each execution of a flow against an environment. The run ID opens that run. |
| **Environments** | Deploy targets |
| **Databases** | Declared DB models, posture, apply records — see [databases](../databases/index.md) |

Flows is the tab Deployments opens on. Runs live at `/deployments/runs`, and
one run at `/deployments/runs/<run id>`. There is no separate Hosting
destination: hosting shows up as Packs, environment settings (projected
scalar reads only) and the delivery `/yoke onboard` configures for a first
dash that deploys.

## Flows

**Flows** lists every definition you can read, grouped by project with the
projects in the current scope first, and searches names, IDs, stages and
environments. Disabled definitions stay hidden until **Show disabled (N)** is
checked; only a flow that is not active carries a status pill.

The selected flow shows its name and ID, its description, and one facts row:
project, environment, target tier, on failure, and the flow it replaces
(`supersedes_flow_id`, linked). Its pipeline is a numbered list in stage
order, each stage naming what runs it ("GitHub Actions · release.yml",
"Warm-up · prod", "Automatic", "Approval"). QA and approval stages add their
scope, where they run, and who decides; stages a person must decide are
marked. Up to five recent runs of the flow link to their run pages.

On a narrow pane the list comes first, and a chosen flow opens alone with
**‹ All flows** to return. Selecting a flow updates its shareable URL,
survives reload and supports Back. Action dialogs keep keyboard focus inside,
return it on dismissal, and prevent duplicate pending actions. The page has
no controls that change a definition.

Packs distinguish a newer available version from an expired repository
report. Opening an update preview names the selected Pack and project and
moves focus to that preview. Environments and Databases keep unavailable
facts explicit and put detailed technical limitations behind disclosure.

## Runs

**Runs** titles each row with its flow name and puts the run ID beneath it as
the link to the run. The QA evidence column holds a few small thumbnails with
"and N more" beneath; the run page has the rest. The table stacks each row
into labelled lines whenever its content pane cannot hold every column.

The run page reads that exact run across every project the viewer can access,
so its members include work from another project even when opened from a
project-filtered list. The list keeps its chosen project filter; run checks
and the target environment still belong to the run's owning project.

Delivery-run cards show only QA bound to their own run; a run without item QA
shows no item-QA count. Retracted requirements appear as cancelled with their
removal reason and are excluded from pass counts, as are no-obligation
records. Stage age reads only the durable `current_stage_entered_at` clock;
older runs show unknown age.

## Commits made outside Yoke

Commits made outside Yoke ship without an item or attestation. Run pages,
Shipping cards, Runs tables and release approvals show **Also includes N
commits made outside Yoke**. Expand it to see each project's short commit SHA,
subject and author. `yoke merge-receipt commits attest` optionally ties a
commit to its owning item ([carried work](model/runs.md#carried-work)).

## Item cards

Frontier item cards show the newest run that named the item in each
environment, including recorded removals. A removed member reads
"removed · <recorded reason> · rides a later release", or links the newer run
holding it. With no recorded reason it reads "removed · rides" and still
names the later run. A failed or cancelled deployment keeps that outcome even
when its member QA cannot be read, with the QA reason on the same tooltip.

The item page's Delivery card names the run selected by the same
completion-authority read as the done gate: **Delivered by** when delivery
succeeded, **Delivering** while it is in flight, and **Also in** for other
carrying runs. A release from another project can deliver the item when its
recorded bound source has completion authority; matching flow names alone do
not prove delivery.

Each run shows its flow → target environment. Terminal runs show
**finished** (succeeded) or **ended** (failed or cancelled) from
`completed_at`; executing runs show their current stage and **started** from
`started_at` (or `created_at` before execution starts). A missing terminal
timestamp is reported as unavailable, never replaced by the creation time.
The **Item's flow** row is omitted when that flow delivered the item. When
another flow delivered it, the selected flow says **not used: delivered by
the run above**.

## Related

- [Deployments overview](index.md)
- [Sites, environments and flows](model/flows.md)

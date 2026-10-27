# Concepts

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Installation reference](index.md) > Concepts
<!-- /yoke:breadcrumbs -->

## Universe

A universe is one Yoke control-plane database plus the projects, workflows,
strategy docs, events, and delivery state inside it. Local mode births a
universe on your laptop. Cloud and self-hosted each host one (or more) for
your organization.

## Organization (Cloud)

On Yoke Cloud, an organization wraps a hosted universe. Members, billing, and
machine access are organization concerns. The workbench URL looks like
`app.upyoke.com/orgs/<slug>/...`.

## Project

A project is where code deploys and where backlog items are scoped. One work
item targets one project. Cross-project work becomes separate items.

Projects bind:

- a git checkout (or remote)
- GitHub repo (optional, depending on sync mode)
- capabilities, packs, QA plans, delivery flows
- strategy corpus

## Strategy docs

Strategy docs record why a project exists, where it should go and what to
work on next. You meet them when adopting a project or choosing its next
work: **MISSION** states its purpose, **VISION** its chosen future,
**LANDSCAPE** the research, **MASTER-PLAN** the wider plan and
**CURRENT-PLAN** the near-term focus.

Try opening **Strategy** in the workbench and reading the project's current
plan. See [Strategy](../strategy/index.md) for the document roles and how to
write them with `/yoke strategize`.

## Steering

Steering turns a strategy doc into ongoing work: a steering agent staffs
workers, tracks their progress and keeps the plan current. You meet it after
agreeing what the project should pursue; each worker executes its own item
through that item's workflow.

With a strategy doc ready, try `/yoke steer` in a Claude Code or Cursor
session opened in the project folder, or `$yoke steer` in Codex. It uses
**CURRENT-PLAN** by default. See [Agents](../agents/index.md) for the skill
entry points and [Strategy](../strategy/index.md#link-to-items-and-to-a-steering-seat)
for the scope a steering seat covers.

## Items

Work is an item with a public ref like `PREFIX-N`. Content lives in structured
fields (spec, design, plan, …); the rendered body is virtual.

Orthogonal flags: **blocked**, **frozen** — they do not replace lifecycle
status.

## Workflows

Every item pins an immutable workflow version. Built-ins:

| Workflow | For |
|---|---|
| **Dash** | One spec, execute end to end — small through very large |
| **Issue** | Bounded change; item body is the spec |
| **Epic** | Architect decomposition + task lanes |
| **Blitz** | Document-led plan as integrated slices |

See [Workflows](../workflows/index.md) and [workflows/lifecycle.md](../workflows/lifecycle.md).

## Team

**Team** is the workbench page for people and machine accounts, their roles,
access and invitations. You meet it when checking who can act in your
universe or adding a teammate. It is available in local, self-hosted and
Cloud modes; a local universe needs a team server before inviting people.

Try opening **Settings → Team** and checking your role in **People**.
See [Team, Billing, Universe settings](../projects/actors-members-billing.md#team)
for roles, invitations and the differences between modes.

## Workbench destinations

The universe workbench sidenav is the operator map, in three groups. Focus is
the working day: Strategy, Frontier, Items, Shipping, Machines, Sessions, Inbox.
Settings is what persists: Universe, Levels, Workflows, Projects, GitHub,
Team, Billing. Diagnostics is the drawer, closed until you open it:
Deployments, Environments, Databases, QA methods, QA plans, QA activity,
Capabilities, Packs, Architecture, Messages, Launches, Events, Doctor,
Ouroboros. This docs set follows that map.

Search refreshes its catalogs when reopened and offers Retry after a failed
read. Incoming result groups preserve the selected result and keyboard focus.
On narrow screens, the navigation drawer moves focus inside while open and
returns it on dismissal; crossing back to desktop restores the main content.

Architecture shows **Not assessed** when its current inventory contains no
Python files. A declared map remains visible; empty coverage cannot establish
health. Sync the project's file inventory to assess applicable files.

Shipping and Deployments select whole runs by the projects of their carried
items. A selected run always shows its full membership and decisions across
projects; run detail has no project selector. Each item approval keeps that
item's own project authority and appears on the run beside its evidence,
before a shared human run acceptance is requested. Inbox filtering remains
project specific.

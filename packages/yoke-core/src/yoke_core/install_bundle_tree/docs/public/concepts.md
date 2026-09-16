# Concepts

## Universe

A universe is one Yoke control-plane database plus the projects, workflows,
strategy docs, events, and delivery state inside it. Local mode births a
universe on your laptop. Cloud and self-hosted each host one (or more) for
your organization.

## Organization (Cloud)

On Yoke Cloud, an organization wraps a hosted universe. Members, billing, and
machine access are organization concerns. The workbench URL looks like
`app.upyoke.com/orgs/<slug>#/...`.

## Project

A project is where code deploys and where backlog items are scoped. One work
item targets one project. Cross-project work becomes separate items.

Projects bind:

- a git checkout (or remote)
- GitHub repo (optional, depending on sync mode)
- capabilities, packs, QA plans, delivery flows
- strategy corpus

## Items

Work is an item with a public ref like `PREFIX-N`. Content lives in structured
fields (spec, design, plan, …); the rendered body is virtual.

Orthogonal flags: **blocked**, **frozen** — they do not replace lifecycle
status.

## Workflows

Every item pins an immutable workflow version. Built-ins:

| Workflow | For |
|---|---|
| **Dash** | One instruction, execute end to end — small through very large |
| **Issue** | Bounded change; item body is the spec |
| **Epic** | Architect decomposition + task lanes |
| **Blitz** | Document-led plan as integrated slices |

See [Workflows](workflows.md) and [reference/lifecycle.md](reference/lifecycle.md).

## Workbench destinations

The universe workbench sidenav is the operator map, in three groups. Focus is
the working day: Strategy, Frontier, Shipping, Machines, Sessions, Inbox.
Settings is what persists: Universe, Workflows, Projects, GitHub, Actors,
Members, Billing. Diagnostics is the drawer, closed until you open it: Items,
Deployments, Environments, Databases, QA methods, QA plans, QA activity,
Capabilities, Packs, Architecture, Messages, Launches, Events, Doctor,
Ouroboros. This docs set follows that map.

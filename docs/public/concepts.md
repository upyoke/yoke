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
| **Dash** | One instruction, execute end to end |
| **Issue** | Bounded change; item body is the spec |
| **Epic** | Architect decomposition + task lanes |
| **Blitz** | Document-led plan as integrated slices |

See [Workflows](workflows.md) and [reference/lifecycle.md](reference/lifecycle.md).

## Workbench tabs

The universe workbench sidenav is the operator map: Overview, Inbox, Strategy,
Frontier, Items, Sessions, Delivery, QA, Workflows, Capabilities, Events,
Doctor, Ouroboros, Projects, Access, Packs, GitHub, settings, Members, Billing.
This docs set follows that map.

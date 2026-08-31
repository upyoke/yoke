# What Yoke is

Yoke is a control plane for software delivery. Humans set direction and approve
what matters; agents and deterministic workers execute. Strategy, backlog,
dependencies, verification, environments, and deployment share one Postgres-
backed universe.

## What you get

- **Strategy** — a durable planning corpus per project
- **Frontier** — what can run now, and why
- **Items** — work with pinned workflows (Dash, Issue, Epic, Blitz, Task)
- **Sessions** — harness sessions and what they hold
- **Delivery** — environments, flows, runs, databases, infrastructure
- **QA** — methods, plans, and recorded outcomes
- **Doctor / Events / Ouroboros** — health, audit trail, and self-improvement

The same engine runs on your laptop, on a team server, or on Yoke Cloud. The
web workbench and the CLI both talk to that universe.

## How work moves

1. Capture an idea (or let feed materialize work from strategy)
2. Refine until the item is ready
3. Implement in an isolated worktree lane (advance / shepherd / conduct / dash)
4. Verify through attached QA
5. Usher: merge, deploy, record evidence, mark done

`/yoke do` offers the session to Yoke's decision engine when you want the
system to pick the next useful move. Direct commands remain available.

## Read next

- [Modes](modes.md) — Local, Cloud, Self-hosted
- [Install](install.md) — one installer, then onboard
- [Concepts](concepts.md) — universe, projects, items, workflows

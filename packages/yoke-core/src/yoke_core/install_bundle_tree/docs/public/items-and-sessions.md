# Items and Sessions

## Items

Workbench **Items** lists backlog work. Open an item for status, fields,
progress, claims, and QA attachments.

```bash
yoke items get PREFIX-N
yoke items get PREFIX-N body
yoke items progress-log append PREFIX-N --headline TEXT --content TEXT
```

Writes go through structured fields and registered functions — not raw body
files. See [reference/commands.md](reference/commands.md).

## Sessions

Workbench **Sessions** lists harness sessions against this universe: who is
running, what item they hold, mode (dash, conduct, wait, …).

Sessions own work claims. Implementation lanes require an active claim and a
registered worktree. Ending a session releases claims it still holds.

Ambient session identity comes from the harness (env / process anchor /
conversation mapping) — operators should not invent session IDs.

## Overview and Inbox

- **Overview** — glance sections across strategy, frontier, sessions,
  delivery, events, doctor
- **Inbox** — decisions waiting on you (approvals, machine connect, …)

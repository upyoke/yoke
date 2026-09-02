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

An active steering scope appears on the generated board with its holder,
project and held strategy documents, claim age, liveness, steering-launched
worker count, and unacknowledged report count. In Workbench, Steering badges
show the same scope, steering-launched workers group under their holder, and a
covered operator session shows whether its latest turn-end report was sent or
acknowledged. These views derive from existing claims, document locks, launch
provenance, and message-recipient receipts; they do not create separate state.

Ambient session identity comes from the harness (env / process anchor /
conversation mapping) — operators should not invent session IDs.

## Overview and Inbox

- **Overview** — glance sections across strategy, frontier, sessions,
  delivery, events, doctor
- **Inbox** — two panels, because two kinds of thing reach a person: the
  gates waiting on your decision (deploy stage, QA review, lifecycle
  approval) and the messages sent to you. An agent that needs you to know
  something sends a message, with context and a specific ask

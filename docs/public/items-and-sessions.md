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

The roster opens on **Active**, which includes both active sessions and stale
sessions. Stale sessions remain visible as light-red cards with a red `stale`
pill. **Any state** includes ended sessions too, while **Ended** shows only
ended sessions. **Reclaim stale** counts stale rows in the loaded scope and
reloads the roster after cleanup, so reclaimed rows leave Active immediately.

Sessions own work claims. Implementation lanes require an active claim and a
registered worktree. Ending a session releases claims it still holds.

An active steering scope appears on the generated board with its holder,
project and held strategy documents, claim age, liveness, steering-launched
worker count, and unacknowledged report count. In Workbench, Steering badges
show the same scope, steering-launched workers group under their holder, and
each of those workers shows whether its latest turn-end report was sent or
acknowledged. Only a steering-launched session is relayed that way: a session
the operator launched or opened keeps its turns to itself and reaches the seat
deliberately with `yoke say --steering`. The relay carries only a turn that
names something to act on — a failure, a blocker, a conflict, a decision, a
question, or a terminal outcome. A worker stopping on a wait or a status note
is recorded as a `SteeringReportSkipped` event rather than delivered, so a
long gate costs the seat no acknowledgements. These views derive from existing
claims, document locks, launch provenance, and message-recipient receipts;
they do not create separate state.

Ambient session identity comes from the harness (env / process anchor /
conversation mapping) — operators should not invent session IDs.

`yoke sessions hook-overhead [--hours N]` summarizes hourly PreToolUse and
PostToolUse client wall time, server time, and their network-plus-startup
remainder. Add `--json` for the registered result envelope.

## Overview and Inbox

- **Overview** — glance sections across strategy, frontier, sessions,
  delivery, events, doctor
- **Inbox** — two panels, because two kinds of thing reach a person: the
  gates waiting on your decision (deploy stage, QA review, lifecycle
  approval) and the messages sent to you. An agent that needs you to know
  something sends a message, with context and a specific ask
- A gate that needs every listed approver shows how far it has got — how
  many of the checked approvers have decided, and who it is still waiting
  on. A gate you already answered reports your own decision instead of
  offering an action you cannot take twice; any rejection ends it outright

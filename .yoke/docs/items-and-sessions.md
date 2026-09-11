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
each of those workers shows whether its latest deliberate report was sent or
acknowledged. Every worker reaches the seat deliberately with `yoke say
--steering`; ending a turn sends no Fleet message. Workers reserve those
messages for something the seat must act on — a failure, blocker, conflict,
decision, question, or terminal outcome — and keep progress in their own
visible output. A report addressed to the role has a recipient whether or not
a seat is live, so sending, previewing, reading, and listing one all report
that recipient's own state: `awaiting_seat` with the scope it is queued for,
`delivered` naming the seat holding it, or `acknowledged`. A queued report is
therefore never a message that went nowhere. These views derive from existing
claims, document locks, launch provenance, and message-recipient receipts;
they do not create separate state.

Ambient session identity comes from the harness (env / process anchor /
conversation mapping) — operators should not invent session IDs.

`yoke sessions hook-overhead [--hours N]` summarizes hourly PreToolUse and
PostToolUse client wall time, evaluator time, and their remainder, then shows
completed tool-call latency beside timed/total coverage globally and per
harness. Missing durations stay unknown rather than becoming zero. The
distinct-session `ACTIVE*` count is a fixed-hour activity proxy, not the live
roster or proof of simultaneous execution. Add `--json` for the registered
result envelope.

`yoke hook benchmark --samples 5 [--json]` runs the harmless system `true`
command between normal PreToolUse and PostToolUse checks. It records direct
pre/command/post/envelope wall times and reads evaluator/client-wall phases
from durable `HookDispatchTelemetry`, with exact timing coverage, harness,
surface, revisions when available, time window, run count, and separately
defined live-roster and running-session proxy counts. Save a JSON report and
compare it with `--compare REPORT.json`; mismatched identity, revisions,
command, or sample count, and incomplete evaluator/client-wall coverage, are
labelled incomparable.

## Overview and Inbox

- **Overview** — glance sections across strategy, frontier, sessions,
  delivery, events, doctor
- **Inbox** — three sections: the decisions waiting on you (a release
  approval, a work approval, or a QA review), the messages sent to you, and
  what you decided while on the page. An agent that needs you to know
  something sends a message, with context and a specific ask
- Every decision is one card, the same card a run draws on the Overview's
  Shipping band and on the run page: what kind of ask it is, what it is
  about, what a yes does in one sentence, the evidence behind it, who
  settles it, and the answer. Screenshots load as thumbnails and open in
  place; stored command output opens as text; evidence held on another
  machine says so. The long form — why you were asked, exactly what
  approving does, the release contents or branch diff — stays one
  disclosure away
- A decision that needs every listed approver counts how far it has got
  and names who it is still waiting on; one that any approver settles names
  the people or the role who can. A card you already answered reports your
  own decision instead of offering an action you cannot take twice; any
  rejection ends it outright
- **Deployments** rows open the run page: the flow, the stages, the checks
  the run's QA recorded with their evidence, what the run carries, and the
  decision waiting on it. QA activity rows and an item's Verification rows
  point a review still waiting on you back at its Inbox card
- A desktop conversation cannot be resumed for you, so a message waiting in
  one raises a notice asking you to open that chat. The notice is derived
  from the waiting message, so it settles itself the moment the wait ends —
  the message was delivered, acknowledged, cancelled, or expired, or that
  conversation ended — and the card leaves the Inbox with the reason on
  record. Nothing else is dismissed for you

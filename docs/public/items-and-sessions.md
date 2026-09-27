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
registered worktree. A persisted active work claim keeps its session live
through stale, idle, parked, process-gone, and startup sweeps. This includes
release waits; parking records the delivery wait for wake routing and does
not determine retention. Claim release, completion, cancellation, and
authorized operator termination free ownership. Explicit session end releases
the claims it still holds. A claim conflict names its holder and requires one
of those explicit actions rather than a heartbeat timeout.

An active steering scope appears on the generated board with its holder,
project and held strategy documents, claim age, liveness, steering-launched
worker count, and unacknowledged report count. In Workbench, Steering badges
show the same scope, steering-launched workers group under their holder, and
each of those workers shows whether its latest deliberate report was sent or
acknowledged. Every worker reaches the seat deliberately with `yoke say
--steering`; ending a turn sends no Fleet message. Workers reserve those
messages for something the seat must act on — a failure, blocker, conflict,
decision, question, or terminal outcome — and keep progress in their own
visible output. A substantive peer request addresses its intended worker with
`--item` (or an exact listed `--session` when no claim addresses the recipient)
and copies the relevant seat by adding `--steering`; those anchors union. The
recipient replies to the original requesting session and also copies steering,
particularly to accept or refuse, report a scope conflict or blocker, or ask
for a decision. A rejection sent only to steering leaves the requester
uninformed. When the sender holds no applicable item, it supplies the explicit
scope with `--steering-scope '{"project_id": N}'`. Session IDs are always copied
whole from a listing, never guessed or reconstructed. Acknowledgement records
receipt, not acceptance or implementation. A report addressed to the role has
a recipient whether or not a seat is live, so sending, previewing, reading, and listing one all report
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
harness. Tool latency re-reads repaired `session_tool_calls` owner timestamps;
a start or client wall still inside the pending-delivery window is pending,
not incomplete. Missing durations outside that window stay unknown rather
than becoming zero. The `--hours` observation cutoff and the pending window
are explicit on the JSON result. The distinct-session `ACTIVE*` count is a
fixed-hour activity proxy, not the live roster or proof of simultaneous
execution. Add `--json` for the registered result envelope.

`yoke hook benchmark --samples 5 [--json]` runs the harmless system `true`
command between normal PreToolUse and PostToolUse checks. It records direct
pre/command/post/envelope wall times and reads evaluator/client-wall phases
from durable `HookDispatchTelemetry`, with exact timing coverage, harness,
surface, revisions when available, time window, run count, and separately
defined live-roster and running-session proxy counts. A phase still in
flight is pending delivery, not incomplete coverage. Save a JSON report and
compare it with `--compare REPORT.json`; mismatched identity, revisions,
command, or sample count, pending delivery, and incomplete
evaluator/client-wall coverage, are labelled incomparable.

## Focus pages and Inbox

- **Strategy** — the corpus itself: standing direction, the plans under
  it, the archive, and the write history below them
- **Frontier** — work in the four states work is in: stopped and why,
  free to pick up, being worked on right now, and finished in the last day
- **Shipping** — each run card lists carried items first; only its run ID
  opens the run page, while item links, screenshots, decisions and
  disclosures keep their own targets. Each carried item's ID and title link to
  the item. An item with a QA requirement leads with **QA for the deployed
  revision** — the check that ran against it, linked to its QA case, with
  **View output** when it recorded output — then that check's screenshots;
  every other check is one row behind a single **Earlier checks** disclosure
  (before merge with its own GitHub Actions run, or an earlier run and
  revision). An item with no QA requirement shows no QA block. One run QA
  section follows the items: each current check names its method (linked to
  its QA case), its outcome, its reason, and the screenshots that check
  captured, each shown once; earlier or superseded checks fold before the
  decision. A run with no run checks and no decision has no run QA section.
  Where a person decides a run's checks, they read **screenshots captured ·
  awaiting approval** and the heading **Awaiting approval** until the
  request is answered with **Reject** or **Approve**, then **approved** (or
  **rejected**) beside the record naming who decided and when. The run page
  uses the same order. A run whose stages are complete but whose
  members are still being settled reads **finalizing** until its authoritative
  status succeeds.
- **Inbox** — three sections: the decisions waiting on you (a release
  approval, a work approval, or a QA review), the messages sent to you, and
  what you decided while on the page. An agent that needs you to know
  something sends a message, with context and a specific ask. A run's own QA
  review is titled **Run QA · <run ID>**, linking the run, and lists the run's
  checks the way Shipping does — each with its own screenshots, earlier
  attempts folded — then the decision
- Every decision is one card, the same card a run draws on Shipping and on
  the run page: what kind of ask it is, what it is
  about, what a yes does in one sentence, who settles it, and the answer.
  A run draws its screenshots once in its QA section. Screenshots load as thumbnails and open in
  place; stored command output opens as text; evidence held on another
  machine says so. The long form — why you were asked, exactly what
  approving does, the release contents or branch diff — stays one
  disclosure away
- A decision that needs every listed approver counts how far it has got
  and names who it is still waiting on; one that any approver settles names
  the people or the role who can. A card you already answered reports your
  own decision instead of offering an action you cannot take twice; any
  rejection ends it outright
- **Deployments** is one page with Flows first and Runs second. A Runs row
  opens the run page: what the release is frozen to, the flow, the stages,
  the checks the run's QA recorded with their evidence, what the run
  carries, and its waiting and resolved decisions. The trail sits above the
  title; the status ends the facts line; the stage rail is a 200px column
  beside the work once the content is wider than 590px. A stopped release
  names the releases that carried the same work after it
- **QA activity** names each case for what ran against what ("Browser
  inspection · run-…", "Command check · PLAT-…"), and that name links to
  the case page — the row itself is not a link. The case page carries the
  same name, a command check's recorded output, its GitHub Actions run when
  the record has one, the contract it had to
  prove, the stage execution whose verdict policy judged it, and what it
  captured. An item's Verification rows point a review still waiting on you
  back at its Inbox card
- The Inbox keeps delivery notices — a QA stage result, an item completing —
  in their own section. They report and ask nothing, so each names which of
  the two events it is and is dismissed rather than answered
- An item page says how it ships: the flow it is bound to, and each release
  that carried it, newest first. A session card says where its release has
  got to and where its item has, as two short statuses
- A desktop conversation cannot be resumed for you, so a message waiting in
  one raises a notice asking you to open that chat. The notice is derived
  from the waiting message, so it settles itself the moment the wait ends —
  the message was delivered, acknowledged, cancelled, or expired, or that
  conversation ended — and the card leaves the Inbox with the reason on
  record. Nothing else is dismissed for you

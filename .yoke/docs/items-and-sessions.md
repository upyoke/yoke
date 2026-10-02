# Items and Sessions

## Items

Workbench **Items** lists backlog work. Open an item for status, fields,
progress, claims, and QA attachments.

New Item keeps a draft through refresh in the same browser tab when session
storage is available. Drafts belong to the signed-in actor and universe;
restoration rechecks the project's creation permissions and workflow settings.
Retry preserves typed fields. Creation clears only the submitted draft; edits
made while creation is pending remain available. A response from a form you
have left cannot navigate you away or erase a newer draft. **Discard draft**
explicitly abandons it. Closing the browser session can remove it.

Narrow layouts show labeled item cards with every sort choice available
above them. Item details place status, ownership, blockers and delivery facts
ahead of long narrative on a phone; the desktop keeps its two-column layout.

The table starts with **Last updated, descending** when the signed-in actor
has no saved sort. Column headers change the sort for the full filtered
dataset before pages load; equal values have a stable item-ID tie break.
The actor's column and direction are saved on the server independently of
project selections and restored across browsers, devices, and reloads.
Returning to Items or bringing its tab back into focus refreshes that choice.
Load or save failures show recovery guidance beside the table; a failed read
keeps the last known order and never saves a default over the stored choice.

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

Held item IDs show Frozen and Blocked pills from the item's own state. If
both apply, Frozen appears first and colors the active workflow segment ice
blue; Blocked remains visible beside it. Blocked alone colors that segment
red. Completed and upcoming segments retain their normal colors. A parked or
idle session does not, by itself, mark its item Frozen or Blocked.

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
  the item. Beneath each carried item, **Item QA** shows that item's checks
  for this run, its screenshots, its earlier attempts, and its own decisions;
  **Run QA** follows every carried item with the run's own checks and
  decisions only. Both are drawn the same way: each current check reads
  **<method> · Passed** (or its actual result) with its status mark, linked to
  its QA case, with the screenshots that check captured, each shown once;
  every other check is one line behind a single **Earlier checks**
  disclosure naming the run it came from or **Before merge** with its GitHub
  Actions run. An item with no QA requirement and no decision shows no Item
  QA; a run with no run checks and no decision has no Run QA. An item's work
  approval — pending with **Reject** and **Approve**, or answered — appears
  only in its Item QA, never under Run QA, with any screenshot of the item's
  current release its checks have not already shown, or a note that none was
  captured. A decision never replaces a check's result: while one is owed
  the heading reads **Awaiting approval**, and once answered the record
  below the evidence names who approved or rejected it, and when. The run
  page uses the same order. A run whose stages are complete but whose
  members are still being settled reads **finalizing** until its authoritative
  status succeeds.
- **Inbox** — three sections: the decisions waiting on you (a release
  approval, a work approval, or a QA review), the messages sent to you, and
  what you decided while on the page. An agent that needs you to know
  something sends a message, with context and a specific ask. A run's own QA
  evidence review is titled **Run QA evidence · <case name>**, linking the run,
  and asks to settle evidence the independent review could not decide with
  **Accept evidence**, **Reject evidence**, and **Waive evidence review**.
  The flow's separate release sign-off is titled **Run approval · <run ID>**
  and asks to approve or reject the release with **Approve release**,
  **Reject release**, and **Waive run approval**. These titles, prompts and
  action labels are identical on Shipping and the run page; answering either
  decision settles only its own requirement. Each card lists the run's
  checks the way Shipping does — each with its own screenshots, earlier
  attempts folded — then the decision. A work approval for a carried item
  shows the screenshots its current release captured for that item —
  including the capture an accepted review judged — and keeps them beside
  the recorded answer once decided
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
  got to and where its item has, as two short statuses. Its item stage strip
  follows a recorded status change after landing, including a return to
  implementation; a merge stamp with no later transition keeps a stale
  earlier status at closeout
- A desktop conversation cannot be resumed for you, so a message waiting in
  one raises a notice asking you to open that chat. The notice is derived
  from the waiting message, so it settles itself the moment the wait ends —
  the message was delivered, acknowledged, cancelled, or expired, or that
  conversation ended — and the card leaves the Inbox with the reason on
  record. Nothing else is dismissed for you

## Effective completion flow reads

`yoke items get PREFIX-N deployment_flow` resolves the item's selected flow
or its project workflow default and prints the source, for example
`flow-name (project default)`. Read `--help` for the field projection.
The JSON field is `{value, source}`; sources are `item`, `project_default`,
`none`, or `unreadable`. Item listings and detail views carry the same
effective value and provenance. An unreadable default stays named rather
than appearing to be an unconfigured item.

`yoke deployment-flows list` keeps each stored stages document in one row;
JSON preserves the complete stored value and text renders stages compactly.
Read `--help` for project and disabled-flow filters.

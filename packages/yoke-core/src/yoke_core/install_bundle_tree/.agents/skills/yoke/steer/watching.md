# Keep the steering watcher attached

After reading the standing plan and checking the session's live mode, start
one fleet watcher covering every held project (repeat `--project` for distinct
projects, even when one project has several document seats):

```text
yoke watch fleet --print-streaming-pair -- --project {_project}
```

Use the existing returned `wait_mode` and reason. The selector reads the
calling harness's declared wake capability and headless launch context. Native
background notifications and Yoke restarting a stopped CLI session are distinct
mechanisms; relay reachability does not grant a native idle notification.
Never claim that an ended desktop turn without native idle wake can receive
background notifications.

- `background-wake`: arm the printed background command and native subscription
  once, using only the mechanism declared for this harness.
- `in-turn`: the invocation already runs the watcher in this turn. Keep its
  tool stream attached and handle incoming work without ending the turn.

<!-- YOKE:HARNESS claude start -->
For the declared native `Monitor` route, run the printed background command
and subscription. On an `in-turn` route keep Bash foreground with its documented
long timeout. Retain a `ScheduleWakeup` fallback of at least 1200 seconds only
when the manifest declares that timer route available.
<!-- YOKE:HARNESS end -->

<!-- YOKE:HARNESS cursor start -->
Use the declared `notify_on_output` subscription when the selector returns
`background-wake`. An `in-turn` result keeps the command foreground; do not
substitute a relay resume for a native subscription.
<!-- YOKE:HARNESS end -->

<!-- YOKE:HARNESS codex start -->
Codex declares no native idle notification. Start the invocation with
`exec_command`; while it returns a running `session_id`, continue it with
`write_stdin`. Yield tool output in bounded intervals so ordinary user questions
can be answered in commentary while work continues. A question or status
request does not cancel the watcher or authorize a final answer that abandons
it. Keep the active stream and resume coordinating after the commentary reply.
<!-- YOKE:HARNESS end -->

The probe checks approximately once a minute. Newly actionable availability
wakes immediately, including dependency clearance without an item status or
claim change. Due reports are checked even without deltas, so cooldown then
quiet and timer-only findings still reach the seat. Fingerprints suppress
unchanged reports; existing idle-holder, unowned-work and undelivered-message
checks remain in force. Pull `yoke steering report get` without a project
filter to reconcile all held project/document scopes.

After compaction, resume, watcher exit, or subscription loss, verify the live
mode and whether this session's watcher is still running. Reattach the existing
stream/subscription if present; otherwise rearm with the same selector command.
Inspect a failed capture's named reason and recovery before retrying. Do not
leave a successful bounded watcher exit as the end of continuous steering.

An explicit **stop looping** request pauses coordination: record pending
message dispositions and operator reminders in the standing plan, stamp
`yoke sessions touch --mode parked --reason "operator paused steering"`, and
stop the watcher through its owning tool handle. Preserve that pause across
ordinary questions, hooks and compaction; no automatic rearm overrides it.
Explicit resumption stamps `yoke sessions touch --mode steer` and rearms the
watcher. A permanent stop follows the release ceremony in `SKILL.md`.

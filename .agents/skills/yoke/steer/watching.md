# Keep the steering watcher attached

After reading the standing plan and checking the session's live mode, start
one fleet watcher covering every held project (repeat `--project` for distinct
projects, even when one project has several document seats):

```text
yoke watch fleet --print-streaming-pair -- --project {_project}
```

That call only prints — it starts no watcher. Read the returned `wait_mode`
and reason, then run the printed command exactly once. The selector reads the
calling harness's declared wake capability and the relay marker a headless
worker carries — its launch context on the turn the relay started, its
resume-attempt id on every turn the relay restarted after that one. Native
background notifications and Yoke restarting a stopped CLI session are distinct
mechanisms; relay reachability does not grant a native idle notification.
Never claim that an ended desktop turn without native idle wake can receive
background notifications.

- `background-wake`: arm the printed background command and native subscription
  once, using only the mechanism declared for this harness.
- `in-turn`: run the printed foreground invocation in this turn. Keep its
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
Codex declares no native idle notification — Codex desktop's scheduled-task
tooling is a separate, timer-driven re-prompt, not a wake the running
conversation receives while idle. When that tooling is available in the
Codex conversation and the operator has not instructed otherwise, start
steering by creating or reusing a scheduled task in that same conversation
that runs every five minutes with the prompt text exactly `keep steering`. Do
not create a duplicate. Honor an explicit operator instruction not to
schedule one: skip creation and rely on the `in-turn` route below instead.
Pause the schedule when the user pauses steering, and remove it when
steering ends. Codex CLI does not expose desktop scheduled-task tooling;
there, keep the watcher attached with the existing route below.

The `in-turn` route is the only wake this harness has: start the invocation
with `exec_command`, and while it returns a running `session_id`, continue
the SAME session with `write_stdin` — never start a second `exec_command`
invocation beside a live one, and never claim that relaunching a fresh
invocation "wakes" the earlier turn; the earlier turn is either still
running (continue it) or already ended (nothing wakes it, and a new
invocation is a new turn, not a resumption). Yield tool output in bounded
intervals so ordinary user questions can be answered in commentary while
work continues. A question or status request does not cancel the watcher or
authorize a final answer that abandons it. Keep the active stream and resume
coordinating after the commentary reply.
<!-- YOKE:HARNESS end -->

The probe checks approximately once a minute. Newly actionable availability
wakes immediately, including dependency clearance without an item status or
claim change — under `background-wake` that means the armed native
subscription fires on the next check; under `in-turn` there is no separate
wake to fire, the already-open stream simply surfaces the finding on its
next check. Due reports are checked even without deltas, so cooldown then
quiet and timer-only findings still reach the seat. Fingerprints suppress
unchanged reports; existing idle-holder, unowned-work and undelivered-message
checks remain in force. A changed report arrives as one wake containing the
whole block — opening marker, hook digest, and closing marker together — so
the seat can act or decide to pull. A delimiter never wakes on its own. Pull
`yoke steering report get` without a project
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

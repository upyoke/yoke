# Keep the steering watcher attached

After reading the standing plan and live mode, select one fleet watcher for
every held project (repeat --project for distinct projects, not document seats):

```text
yoke watch fleet --print-streaming-pair -- --project {_project}
```

Prints only; starts nothing. Read wait_mode/reason, run the printed command
exactly once. Manifest native idle wake differs from relay stopped-CLI resume
markers (launch context, then resume-attempt id). Relay reachability cannot
give an ended desktop turn native background notification.
background-wake arms its declared subscription; in-turn stays attached to
one foreground invocation while incoming work is handled.

<!-- YOKE:HARNESS claude start -->
Use the declared `Monitor` background command/subscription. In-turn stays
Bash foreground at its documented long timeout. Keep ScheduleWakeup fallback
at least 1200 seconds only if the manifest declares that timer available.
<!-- YOKE:HARNESS end -->

<!-- YOKE:HARNESS cursor start -->
Use declared `notify_on_output` only for background-wake. In-turn stays
foreground; relay resume does not substitute for native subscription.
<!-- YOKE:HARNESS end -->

<!-- YOKE:HARNESS codex start -->
Codex has no native idle notification. If desktop scheduled-task tooling is
available in this conversation and the operator has not opted out, create or
reuse one task every five minutes with exact prompt `keep steering`, never a
duplicate. Pause with user pause; remove when steering ends. CLI has no desktop
task tool. An explicit opt-out uses in-turn instead.

Start in-turn with `exec_command`; continue the SAME running session_id using
`write_stdin`. Never relaunch beside it or call a fresh invocation a wake of
the old turn. Yield bounded output so ordinary questions are answered in
commentary while work continues; a question/status request does not cancel
the watcher or authorize a final answer abandoning it.
<!-- YOKE:HARNESS end -->

Approximately minute cadence checks dependency-cleared availability even
without status/claim deltas; due cooldown/timer findings are checked without
deltas too. Fingerprints suppress unchanged reports. Background uses armed
native subscription; in-turn surfaces findings in its existing stream.
Changed reports wake with the whole opening/digest/closing block, never a
delimiter alone. Pull yoke steering report get without project filter for
all held scopes; retain idle/unowned/undelivered triage.

After compaction, resume, watcher exit or subscription loss, verify live mode
and existing process. Reattach its stream/subscription; rearm only if absent.
Read failed capture's named reason/recovery before retry. Successful bounded
exit is not the end of continuous steering.

An explicit **stop looping** stamps --mode parked with reason operator paused steering,
records message dispositions/reminders in the plan and stops the watcher via
its owning handle. Preserve pause across ordinary questions, hooks and
compaction. Explicit resume stamps --mode steer and rearms; permanent stop
uses [close-out.md](close-out.md).

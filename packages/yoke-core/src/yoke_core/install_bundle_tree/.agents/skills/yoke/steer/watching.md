# Watcher

```text
yoke watch fleet --print-streaming-pair -- --project {_project}
```

Prints only. Run once; repeat `--project` per project.

<!-- YOKE:HARNESS claude start -->
Arm `Monitor` at manifest `idle_wake_deadline_parameter` maximum;
on expiry re-arm the same `yoke watch tail`, never the wrapper.
<!-- YOKE:HARNESS end -->

<!-- YOKE:HARNESS cursor start -->
Use `notify_on_output` only for background-wake.
<!-- YOKE:HARNESS end -->

<!-- YOKE:HARNESS codex start -->
Without background wake, if Codex desktop tasks exist and no opt-out,
keep one five-minute task. The full prompt/message is exactly
`Keep steering`: no status, item lists, identifiers, cold-start or handoff text.
On wake, steer entry reads claimed strategy docs and Live status
for scope, facts and operator boundaries; keep state there.
Remove when steering ends; after an explicit stop, recreate only on operator resume.
Continue `exec_command` via `write_stdin`; never relaunch.
<!-- YOKE:HARNESS end -->

Handle `fleet ALARM` this turn ([fleet-findings.md](fleet-findings.md)).
Run the command in `FLEET WATCHER ALERT`.

**Stop looping**: park (`operator paused steering`); stop the watcher.
On operator resume only: `yoke sessions touch --mode steer` and re-arm.

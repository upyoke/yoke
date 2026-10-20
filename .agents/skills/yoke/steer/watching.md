# Keep the steering watcher attached

```text
yoke watch fleet --print-streaming-pair -- --project {_project}
```

This prints and starts nothing. Run the printed command once; repeat
`--project` for each held project.

<!-- YOKE:HARNESS claude start -->
Arm `Monitor` at the manifest's `idle_wake_deadline_parameter` maximum; on
expiry, re-arm the same `yoke watch tail`. Never relaunch the wrapper.
<!-- YOKE:HARNESS end -->

<!-- YOKE:HARNESS cursor start -->
Use `notify_on_output` only for background-wake.
<!-- YOKE:HARNESS end -->

<!-- YOKE:HARNESS codex start -->
If desktop scheduled tasks exist and the operator has not opted out, keep one
five-minute task with prompt `keep steering`; remove it when steering ends.
Continue the in-turn `exec_command` with `write_stdin`; never relaunch it.
<!-- YOKE:HARNESS end -->

Act on each `fleet ALARM` line the same turn ([fleet-findings.md](fleet-findings.md)).
On a `FLEET WATCHER ALERT`, run the re-arm command it names.

**Stop looping**: park with reason `operator paused steering` and stop the
watcher; resume with `yoke sessions touch --mode steer` and re-arm.

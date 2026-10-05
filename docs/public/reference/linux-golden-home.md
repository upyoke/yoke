# Linux golden-home capture and restore

The complete preparation, saving, restoration and timeout-recovery procedure is
Linux provisioning at `docs/packs/machine-qa/linux-host-provisioning.md` (installed by the Machine QA Pack).
It installs at `docs/packs/machine-qa/linux-host-provisioning.md` with the
Machine QA Pack. Its audit distinguishes live evidence from unverified steps.

Linux reset gives systemd user service mutations the relay's shared 180-second
operation budget; inventory queries retain their 30-second limit. A
`linux_yoke_service_command_timeout` names the command and budget. Its job may
still be running: inspect the reported job before retrying the sealed baseline.
Failed archive operations retain bounded, redacted native exit/stdout/stderr in
the receipt and exploratory-mission preparation, even without a JSON receipt.

Linux and Windows/WSL2 reset probe `yoke`, `uv` and `uvx` separately on login
and SSH shells. Only a framed absolute resolved path counts as present;
unrelated shell startup output does not. `tool_resolution` retains each tool's
state (`absent`, `present`, `probe-failed`), shell and resolution exit codes,
resolved path, and bounded redacted stdout/stderr. `reset_tool_probe_failed`
requires repairing the named shell or SSH probe before retrying; surviving
paths refuse as `reset_absence_not_proved`. Presence summaries are unknown
(`null`) when probes failed without observing a path.

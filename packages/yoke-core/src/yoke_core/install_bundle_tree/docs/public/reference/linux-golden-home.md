# Linux golden-home capture and restore

The complete preparation, saving, restoration and timeout-recovery procedure is
[Linux provisioning](../../../packs/machine-qa/versions/1.3.7/files/docs/packs/machine-qa/linux-host-provisioning.md).
It installs at `docs/packs/machine-qa/linux-host-provisioning.md` with the
Machine QA Pack. Its audit distinguishes live evidence from unverified steps.

Linux reset gives systemd user service mutations the relay's shared 180-second
operation budget; inventory queries retain their 30-second limit. A
`linux_yoke_service_command_timeout` names the command and budget. Its job may
still be running: inspect the reported job before retrying the sealed baseline.
Failed archive operations retain bounded, redacted native exit/stdout/stderr in
the receipt and exploratory-mission preparation, even without a JSON receipt.

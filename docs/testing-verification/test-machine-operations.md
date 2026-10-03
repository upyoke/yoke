# Test Machine operation contracts

Host preparation, sign-in, permissions, desktop access, save/restore and their
recoveries have one authoritative procedure per OS in the Machine QA Pack:

- [macOS](../../packs/machine-qa/versions/1.3.7/files/docs/packs/machine-qa/macos-host-provisioning.md)
- [Linux](../../packs/machine-qa/versions/1.3.7/files/docs/packs/machine-qa/linux-host-provisioning.md)
- [Windows/WSL2](../../packs/machine-qa/versions/1.3.7/files/docs/packs/machine-qa/windows-host-provisioning.md)

See the [provisioning index](../../packs/machine-qa/versions/1.3.7/files/docs/packs/machine-qa/host-provisioning.md).
These procedures install at `docs/packs/machine-qa/`; installed files belong
to the project. This page describes execution and evidence contracts.

A Test Machine capability owns its settings, credentials, QA leases and
operation receipts. Capacity registration owns agent-launch capacity and relay
identity independently, even when both records name one physical host.
The `os` field selects macOS Terminal.app, Linux tmux/XFCE, or Windows OpenSSH
with the dedicated account's default non-root WSL2 user.

The registered commands are discoverable through `yoke test-machine --help`;
each operation's `--help` owns its arguments and output contract. Verify,
reset, golden capture, bridge diagnosis and screenshot each take the host's
one lease and record a receipt. Desktop access also respects the serial host
lease. The machine page shows the last receipt per operation. A successful
reachability read does not establish baseline readiness.

During an awaiting Machine QA mission, these commands automatically reuse its
host lease when the calling session and actor own the mission. Submission and
operation abort retain the lease; the mission's close-out releases it. A foreign
holder refuses with `mission_operation_foreign_holder`: ask the mission holder
to run the operation or wait for it to finish. A plan outside its mission walk
refuses with `mission_operation_unavailable`; resume its mission first.
Calls without a mission retain exclusive acquire/release behavior. Repeated
mission operations update the last receipt; identical retries reuse evidence.
Golden-capture contracts bind their destination and omit the baseline pointers
they update, so recording a capture does not invalidate its submission retry.

Verification distinguishes `ssh` and `terminal_bridge` surfaces as passed,
failed or not_run. A failed bridge leaves overall status error while a passing
transport remains visible. Baseline operations retain their own resulting-state
and absence evidence instead of silently rewriting the verification result.

Linux archive failure receipts retain bounded, redacted native exit/stdout/stderr
through mission preparation. Service mutation timeouts name the command and
budget and warn that its systemd job may still be running.

A screenshot receipt carries a typed QA artifact handle, SHA-256, dimensions
and OS. The CLI exposes its accepted PNG in a private temporary directory for
review. Submission retries adopt the same handle. Failed, malformed or blank
captures have no passing artifact. A transcript cannot substitute for a frame
of the real interactive display. Started/reused desktop identity is operational
evidence, not permission to displace a human session.

Windows session-state reads allow a bounded 45 seconds for native PowerShell
initialization after boot. An unreadable WTS result refuses desktop startup
and records the query exit status and bounded, redacted stdout/stderr. SSH
timeouts retain partial diagnostics so cold initialization can be distinguished
from a broken session query.

Ad hoc `exec` uses the workstation SSH agent, records no QA verdict or operation
receipt, and refuses another session's host lease. It streams stdout/stderr and
keeps bounded failure diagnostics. Mission host commands instead run through
the mission's retained lease; GUI-context commands use its declared GUI route.
The remote shell interprets command text, so argv quoting remains significant.

Bridge diagnosis orders capabilities by their preconditions. A failed
precondition leaves later checks not_run rather than manufacturing extra
failures. Rows retain the classified condition and bounded diagnostic evidence.
On a busy Mac, activation can complete before focus changes; the bridge waits
for the target window to become frontmost before typing. Focus/transcript
timeouts report the measured load that sized their wait, allowing a focus race
to be distinguished from an unavailable privacy grant.

[Testing and verification](../testing-verification.md) covers plan and case
ownership; [baseline semantics](test-machine-golden-baseline.md) covers seals.

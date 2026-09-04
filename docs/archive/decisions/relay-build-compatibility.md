# Relay build compatibility

A machine relay must not execute native work when its source checkout is
newer than the control-plane build serving it. Request models are strict, and
silently translating a newer relay into an older wire dialect would hide the
deployment gap while allowing behavior the server cannot represent.

Before polling for work, the relay performs a stable read through the normal
function transport. The existing HTTPS handshake relates the loaded source
checkout to the server build. An `ahead` relationship is persisted locally as
`relay_newer_than_server`, including both revisions and the `deploy` recovery.
The relay then publishes that health fact without accepting a job. The server
stores the heartbeat but returns no work while the refusal is present, so the
fleet report and `yoke relay status` show an explicit refusal rather than a
silent liveness gap. A later equal-build observation clears the refusal.

Terminal report delivery remains a separate durability boundary. A transport
failure remains queued indefinitely. A server rejection that proves the
report payload cannot be accepted is retried only a bounded number of times,
then moved to a machine-local quarantine with body-free metadata and a log
line naming the server reason. Removing it from the pending queue lets the
poll reach the claim boundary again; build compatibility then independently
decides whether the relay may execute work.

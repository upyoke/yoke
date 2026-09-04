# Relay release and build compatibility

The standing machine relay speaks exactly the contract served by its selected
control-plane environment. Its launch agent executes a relay-owned venv under
the relay instance state directory, never a source checkout. `yoke relay
install` installs the environment's exact immutable `yoke-core` build from its
distribution index; release metadata pins every Yoke sibling wheel to that
same build.

A successful poll's existing HTTPS handshake is the only deploy-change signal.
When its served build differs from the installed receipt, the daemon installs
a candidate beside the working venv, atomically repoints the stable `venv`
link, stops leasing, drains in-flight jobs, and replaces its process. It has no
source-fingerprint watcher, scheduled reload, or timer-driven pin check.

If the manifest, index, or wheel cannot be fetched, the named
`relay_release_fetch_failed` refusal records recovery and preserves the prior
process and pin. `yoke relay status` shows the pinned release, freshly served
build, error, and retry command side by side.

Source development uses `yoke relay serve-once` by hand from a claimed lane.
That one-shot path performs a stable read before polling and refuses native
work when the checkout is newer than the server. An `ahead` relationship is
persisted locally as `relay_newer_than_server`, including both revisions and
the `deploy` recovery. The server stores the heartbeat but returns no work
while the refusal is present, so the fleet report and status show the refusal
rather than a silent liveness gap. A later equal-build observation clears it.

Terminal report delivery remains a separate durability boundary. A transport
failure remains queued indefinitely. A server rejection that proves the
report payload cannot be accepted is retried only a bounded number of times,
then moved to a machine-local quarantine with body-free metadata and a log
line naming the server reason. Removing it from the pending queue lets the
poll reach the claim boundary again; build compatibility then independently
decides whether the relay may execute work.

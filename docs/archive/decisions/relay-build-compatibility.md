# Relay release and build compatibility

The standing machine relay speaks exactly the contract served by its selected
control-plane environment. Its launch agent's stable `venv` link always targets
one fixed `runtime` directory and copied relay-owned Python, never a global
Python or source checkout. It starts in isolated mode so a prior release's
environment cannot run startup code; the small bootstrap then resolves the
active `release` pointer once per process and exports only that physical
release's packages to itself and supervised Python children.
`yoke relay install` installs the environment's exact immutable `yoke-core`
build from its distribution index; release metadata pins every Yoke sibling
wheel to that same build.

The stable identity prevents ordinary updates and restarts from repeatedly
presenting a new executable to macOS. It does not require Developer Tools
Access or a blanket onboarding/iCloud approval; consent remains conditional on
a launched tool actually touching protected or iCloud-backed content.

A successful poll's existing HTTPS handshake is the only deploy-change signal.
When its served build differs from the installed receipt, the daemon installs
a candidate beside the working release, atomically repoints the `release`
link, stops leasing, drains in-flight jobs, and execs the unchanged runtime
entrypoint. Ordinary updates never replace the permission-bearing interpreter;
a full launchd restart also starts through that same physical identity. It has
no scheduled reload or timer-driven pin check; only fresh handshakes drive it.

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

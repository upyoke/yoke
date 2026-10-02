# Linux golden-home capture and restore

Linux Test Machines allow up to 20 minutes for the remote golden-home archive
step, for both capture and restore. This accommodates large homes on small
hosts without changing the archive format or compression. Capture succeeds
only after the archive completes and its declared probes are written beside it;
a timed-out capture is not registered as a golden baseline.

`linux_golden_operation_timeout` reports the operation, measured elapsed seconds,
the timeout bound, and the exact golden destination. Disconnecting the SSH client
does not prove that the remote archive process stopped. Stop or wait for that
process before retrying.

For capture, the refusal names the possible unregistered `home.tar.gz` and
`manifest.json` paths. Inspect that destination and any sibling `.yoke-golden-*`
temporary directory belonging to this capture. Remove its unregistered output
only after the process stops, or capture to a new literal directory outside the
test user's home. A leftover archive has no probes seal and must not be used
for reset.

For restore, the home may be partly restored. After the process stops, retry the
existing sealed baseline. Never capture that mixed home as a new golden.

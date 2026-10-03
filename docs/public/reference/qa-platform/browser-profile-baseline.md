# Saved browser profiles on test machines

A saved browser profile is a separate part of the test machine baseline.
Its setup gives the user space to perform whatever sign-ins their project
needs, then saves the stopped profile. Agents complete steps that do not need
the user; credential entry remains a human gate.

Use the [Machine QA Pack per-OS procedures](../../../../packs/machine-qa/versions/1.3.8/files/docs/packs/machine-qa/browser-profile-baseline.md)
for desktop preparation, capture and restoration. After installation, those
procedures live at `docs/packs/machine-qa/host-provisioning.md`.
The profile stays separate from the clean-home golden and is restored only
after candidate installation, before the candidate browser starts.

Snapshot capture and restore create missing directories with owner-only
permissions. Existing directories keep their permissions; an unsafe credential
directory is refused with its path so the operator can inspect it before retrying.
A snapshot can sit beside a clean golden under a test-user-owned readable
parent, while the snapshot and its files remain owner-only. A parent writable
by other users is refused with its path; capture never chmods that parent.

Restore failures remain closed and prevent browser startup. Unexpected failures
name the operation (`manifest_read`, `manifest_parse`, `archive_open`,
`archive_read`, `extraction`, `permission`, or `profile_resolution`), error class,
content-free message and recovery in both JSON and terminal output. File names,
manifest contents and archive member names are never copied from exceptions.
Existing security refusals keep their named reason.

For a malformed manifest or damaged archive, preserve the rejected snapshot and
capture the stopped signed-in profile into a new sibling through
`yoke test-machine golden-capture --project P --machine NAME --component browser-profile`.
Never hand-edit the sealed capture or weaken its identity, digest, ownership or
archive checks. For filesystem failures, inspect the selected path as the test
user and repair access before retrying.

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

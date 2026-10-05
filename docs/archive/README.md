# docs/archive/

Historical records preserved for reference. Files here are **not** active
documentation — they record the state of past implementations, audits,
migration proofs, and incident follow-ups.

## What belongs here

- Migration proof documents that captured the state during a transition.
- Incident follow-up documents that recorded a specific event window.
- Audit snapshots that are superseded by current tooling.
- Historical design/architecture documents no longer reflecting the live
  system.
- Design specifications that predated implementation and have since been
  superseded by operational docs.

## What does NOT belong here

- Active operator guidance (keep in `docs/`).
- Current reference docs (keep in `docs/`).
- Living architecture docs (keep in `docs/`).
- Project-local policy and operational guidance — keep those in the project's
  own checkout.

## Using archived content

Archived source names identify historical implementations. Do not execute an
archived command or resolve an old identifier as a current file. Current
migration authority is the [database doctrine](../public/reference/agent-rules/databases.md);
current operations are the registered `yoke` commands and their `--help`.
Repair broken navigational links; retain retired names only where they explain
the historical record. When a current doc needs content from an archive,
copy the still-accurate portion into the live doc as present-tense guidance.

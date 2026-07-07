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
- Per-project surfaces — those live under `projects/{project}/`.

## Using archived content

Archive files are read-only for practical purposes. Links inside archived
files may point at retired commands, deleted paths, or obsoleted surface
names; that is expected. When a current doc needs content from an archive
file, copy the still-accurate portion over to the live doc and rewrite it
as present-tense current-state prose — do not link out to the archive.
